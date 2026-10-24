from datetime import datetime
from flask_login import UserMixin
from extensions import db

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text)
    
    first_name = db.Column(db.String(100)) 
    last_name = db.Column(db.String(100))
    
    profile_path = db.Column(db.String(255), nullable=True)
    
    role = db.Column(db.String(20), default="customer") 
    # Job function from the thesis (Owner/Admin, Counter Staff, Inventory
    # Custodian, Delivery Personnel). `role` still controls route access.
    staff_position = db.Column(db.String(40), nullable=True)
    
    google_id = db.Column(db.String(255), unique=True)
    oauth_provider = db.Column(db.String(50))
    
    is_verified = db.Column(db.Boolean, default=False)
    email_verified_at = db.Column(db.DateTime)
    failed_login_attempts = db.Column(db.Integer, default=0)
    account_locked_until = db.Column(db.DateTime)
    lock_reason = db.Column(db.String(255))
    
    reset_otp_code = db.Column(db.String(255), nullable=True)
    reset_code_expiry = db.Column(db.DateTime, nullable=True)
    last_otp_sent = db.Column(db.DateTime, nullable=True)
    password_last_reset_at = db.Column(db.DateTime, nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer_profile = db.relationship("Customer", back_populates="user", uselist=False, foreign_keys="[Customer.user_id]")
    
    last_login_user_agent = db.Column(db.String(255), nullable=True)
    
    permissions = db.relationship("Permission", backref="user", uselist=False)
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def masked_email(self):
        if not self.email or '@' not in self.email:
            return None

        try:
            name, domain = self.email.split('@', 1)

            if len(name) <= 1:
                return self.email
            if len(name) == 2:
                masked_name = name[0] + '*'
            else:
                masked_name = name[0] + ('*' * (len(name) - 2)) + name[-1]

            return f"{masked_name}@{domain}"
        except Exception:
            return None

class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)
    
    can_manage_customers = db.Column(db.Boolean, default=False)
    can_verify_customers = db.Column(db.Boolean, default=False)
    
    can_manage_products = db.Column(db.Boolean, default=False)
    can_update_stock = db.Column(db.Boolean, default=False)

    can_process_transactions = db.Column(db.Boolean, default=False)
    can_confirm_payments = db.Column(db.Boolean, default=False)
    can_export_transactions = db.Column(db.Boolean, default=False)

    can_manage_expenses = db.Column(db.Boolean, default=False)
    can_view_reports = db.Column(db.Boolean, default=False)
    can_view_logs = db.Column(db.Boolean, default=False)
    can_view_active_rentals = db.Column(db.Boolean, default=False)
    
class SecurityLog(db.Model):
    __tablename__ = "security_logs"

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45))
    event_type = db.Column(db.String(100))
    description = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    user_email = db.Column(db.String(120), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    severity = db.Column(db.String(20), default='Low')  # Low / Medium / High / Critical
    is_suspicious = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("security_logs", lazy="dynamic"))
 
 
class BlockedIP(db.Model):
    __tablename__ = "blocked_ips"
 
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), unique=True, nullable=False)
    reason = db.Column(db.String(255))
    blocked_at = db.Column(db.DateTime, default=datetime.utcnow)
    blocked_until = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    blocked_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
 
    admin = db.relationship("User", foreign_keys=[blocked_by],
                            backref=db.backref("blocked_ips_created", lazy="dynamic"))

