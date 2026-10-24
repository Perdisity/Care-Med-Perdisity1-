from gevent import monkey
monkey.patch_all()

import os
from flask import Flask, request, redirect, url_for, flash, render_template, abort
from flask_login import current_user
from extensions import db, migrate, login_manager, oauth, mail, csrf, limiter
from models.users import User
from models.customer import Customer
from models.product import Product, Purchase, Rental, InventoryLog
from flask_talisman import Talisman
from models.users import SecurityLog, BlockedIP
from models.operations import StockAdjustment, VoidRequest
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from flask_login import current_user, logout_user
from datetime import datetime, timezone, timedelta
from flask import session, g
from werkzeug.middleware.proxy_fix import ProxyFix
from models.settings import SystemSetting, parse_deposit_tiers


app = Flask(__name__)
app.jinja_env.globals['enumerate'] = enumerate

if os.environ.get('FLASK_ENV') == 'development':
    app.config.from_object('config.DevConfig')
else:
    app.config.from_object('config.Config')

# Trust proxy headers (Essential for Nginx / reverse proxy setup on DigitalOcean)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)
oauth.init_app(app)
mail.init_app(app)
csrf.init_app(app)
limiter.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


login_manager.login_view = 'auth.login'

csp = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "https://cdnjs.cloudflare.com", "https://www.gstatic.com"],
    "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com", "https://cdnjs.cloudflare.com"],
    "font-src": ["'self'", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"],
    "img-src": ["'self'", "data:", "https://www.google.com", "https://*.googleusercontent.com"],
    "connect-src": ["'self'"],
    "frame-ancestors": ["'self'"],
    "object-src": ["'none'"]
}

Talisman(
    app,
    content_security_policy=csp,
    content_security_policy_nonce_in=["script-src"],
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    strict_transport_security_include_subdomains=True,
    session_cookie_secure=app.config.get('SESSION_COOKIE_SECURE', True),
    session_cookie_http_only=True,
    frame_options="SAMEORIGIN",
)

@app.template_filter('pst')
def utc_to_pst(dt, fmt='%m/%d %H:%M:%S'):
    if not dt:
        return ''
    pst = timezone(timedelta(hours=8))
    aware = dt.replace(tzinfo=timezone.utc).astimezone(pst)
    return aware.strftime(fmt)


# IDS: Block requests from blocked IPs before they reach any route 
@app.before_request
def check_blocked_ip():
    ip = request.remote_addr
    blocked = BlockedIP.query.filter_by(ip_address=ip, is_active=True).first()
    if blocked:
        from datetime import datetime
        if blocked.blocked_until and blocked.blocked_until < datetime.utcnow():
            # Temporary block has expired — deactivate it
            blocked.is_active = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        else:
            abort(403)


@app.before_request         
def enforce_admin_session_timeout():
    """
    Extra safety net:
    - Admins have a 2-hour idle timeout (on top of Flask-Login session_protection).
    - If an admin's session has no 'last_active' timestamp, set it now.
    - If idle for more than 2 hours, log them out and redirect to login.
    """
    if current_user.is_authenticated and current_user.role.strip() == 'Administrator':
        now = datetime.utcnow()
        last_active = session.get('last_active')
 
        if last_active:
            last_active_dt = datetime.fromisoformat(last_active)
            idle_minutes = (now - last_active_dt).total_seconds() / 60
            if idle_minutes > 120:   # 2 hours
                # Log the expiry BEFORE clearing the session
                try:
                    from models.users import SecurityLog
                    from extensions import db
                    expiry_log = SecurityLog(
                        ip_address=request.remote_addr,
                        event_type='Admin Session Expired',
                        description=f"Admin session auto-expired after {int(idle_minutes)} min of inactivity.",
                        user_id=current_user.id,
                        user_email=current_user.email,
                        user_agent=request.headers.get('User-Agent', 'Unknown')[:255],
                        severity='Low',
                        is_suspicious=False
                    )
                    db.session.add(expiry_log)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
 
                logout_user()
                session.clear()
                flash("Your admin session expired due to inactivity. Please log in again.", "warning")
                return redirect(url_for('auth.login'))
 
        # Update last active timestamp on every request
        session['last_active'] = now.isoformat()


# Rate-limit handler: log to IDS + return user-friendly response 
@app.errorhandler(429)
def ratelimit_handler(e):
    try:
        new_log = SecurityLog(
            ip_address=request.remote_addr,
            event_type="Rate Limit Violation",
            description=f"IDS: IP hit rate limit at endpoint '{request.endpoint}'",
            user_id=current_user.id if current_user.is_authenticated else None,
            user_email=current_user.email if current_user.is_authenticated else None,
            user_agent=request.headers.get('User-Agent', 'Unknown')[:255],
            severity='High',
            is_suspicious=True
        )
        db.session.add(new_log)
        db.session.commit()
    except Exception as err:
        print(f"IDS logging failed: {err}")
        db.session.rollback()

    import time
    server_time = int(time.time())

    retry_after = 300  
    try:
        if hasattr(e, 'retry_after') and e.retry_after:
            retry_after = int(e.retry_after)
    except Exception:
        pass

    if request.endpoint == "auth.login":
        message = "Too many login attempts were made from your IP address. For your security, please wait before trying again."
        back_url = url_for("auth.login")
        back_label = "Back to Login"
    else:
        message = "Our system detected an unusual number of requests from your IP address. Access has been temporarily restricted to protect the platform."
        back_url = url_for("user.homepage")
        back_label = "Return to Home"

    deadline = server_time + retry_after

    return render_template(
        'errors/429.html',
        message=message,
        back_url=back_url,
        back_label=back_label,
        deadline=deadline,        
        retry_after=retry_after
    ), 429
    
@app.errorhandler(403)
def forbidden_handler(e):
    from models.users import BlockedIP
    from datetime import datetime, timezone, timedelta

    ip = request.remote_addr
    blocked = BlockedIP.query.filter_by(ip_address=ip, is_active=True).first()

    block_until = None
    is_permanent = False

    if blocked:
        if blocked.blocked_until:
            pst = timezone(timedelta(hours=8))
            block_until_pst = blocked.blocked_until.replace(tzinfo=timezone.utc).astimezone(pst)
            block_until = block_until_pst.strftime('%B %d, %Y at %I:%M %p') + ' PST'
        else:
            is_permanent = True

    return render_template(
        'errors/403.html',
        block_until=block_until,
        is_permanent=is_permanent
    ), 403


@app.template_filter('currency')
def currency(value):
    from decimal import Decimal
    try:
        value = value or Decimal("0.00")
        return f"₱{value:,.2f}"
    except Exception:
        return "₱0.00"


@app.context_processor
def inject_business_rules():
    """Expose owner-editable rules to every template (FR02, RULE-03, RULE-09, RULE-10)."""
    if "biz" not in g:
        g.biz = {
            key: row.as_python()
            for key, row in SystemSetting.all_effective().items()
        }
    try:
        parsed_tiers = parse_deposit_tiers(g.biz.get("deposit_distance_tiers"))
    except ValueError:
        parsed_tiers = []
    deposit_tiers_json = [
        {
            "max_km": float(tier["max_km"]) if tier["max_km"] is not None else None,
            "amount": float(tier["amount"]),
            "label": tier["label"],
        }
        for tier in parsed_tiers
    ]
    return {"biz": g.biz, "deposit_tiers_json": deposit_tiers_json}

    
@app.route('/')
def root():
    if current_user.is_authenticated:
        if current_user.role == 'Administrator':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.products'))
    return redirect(url_for('user.homepage'))

from routes.user_routes import user_bp
app.register_blueprint(user_bp)

from routes.auth_routes import auth_bp
app.register_blueprint(auth_bp)

from routes.admin_routes import admin_bp
app.register_blueprint(admin_bp)

# Admin/staff routes are already gated by admin_or_staff_required (login + role
# check) on every view, independent of the rate limiter. The global 200/day,
# 50/hour default is meant for public/customer traffic and is too tight for a
# full day of real admin work, so authenticated admin/staff traffic gets a
# much higher ceiling instead. This is kept non-zero (rather than a full
# limiter.exempt) as defense-in-depth in case an admin/staff session is ever
# compromised or a client-side bug causes runaway requests.
limiter.limit("1000 per hour")(admin_bp)

# ── Auto Backup Scheduler ──────────────────────
from utils.backup import auto_backup
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=auto_backup,
        trigger='cron',
        hour=0,
        minute=0,
        id='daily_backup',
        replace_existing=True
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    print("[Backup] Scheduler started — auto backup runs every midnight")


if __name__ == "__main__":
    debug = os.environ.get("DEBUG", "False") == "True"
    app.run(debug=debug)