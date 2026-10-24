from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from argon2 import PasswordHasher
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import os

# Load .env before any extension reads os.environ (config.py is imported later)
load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
passhasher = PasswordHasher(time_cost=2, memory_cost=102400, parallelism=8)
oauth = OAuth()
mail = Mail()
csrf = CSRFProtect()


def rate_limit_key():
    """Rate-limit logged-in users by account, not by IP."""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()

limiter = Limiter(
    key_func=rate_limit_key,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "redis://redis:6379/0"),
    default_limits=["200 per day", "50 per hour"]
)
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"