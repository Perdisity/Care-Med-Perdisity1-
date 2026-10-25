import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable is not set")

    uri = os.environ.get("DATABASE_URL")
    if not uri:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    # Fix for SQLAlchemy scheme incompatibility with DigitalOcean/Heroku postgres URLs
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = uri

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 10,
        "max_overflow": 20,
    }

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    SESSION_COOKIE_NAME = "caremed_session"
    SESSION_COOKIE_SECURE = True        
    SESSION_COOKIE_HTTPONLY = True      
    SESSION_COOKIE_SAMESITE = "Lax"  
    
    REMEMBER_COOKIE_DURATION    = timedelta(hours=8)  
    REMEMBER_COOKIE_SECURE      = True
    REMEMBER_COOKIE_HTTPONLY    = True
    REMEMBER_COOKIE_SAMESITE    = "Lax"
    PERMANENT_SESSION_LIFETIME  = timedelta(hours=2)   

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  

    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        raise RuntimeError("MAIL credentials are not configured")

    MAIL_DEFAULT_SENDER = (
        os.environ.get("MAIL_SENDER_NAME", "CareMed Security"),
        MAIL_USERNAME
    )
    MAIL_MAX_EMAILS = 5
    MAIL_TIMEOUT = 10
    MAIL_ASCII_ATTACHMENTS = False

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "X-XSS-Protection": "1; mode=block",
    }
    
    
class DevConfig:

    DEBUG = True
    TESTING = False

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    uri = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = uri

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    SESSION_COOKIE_NAME = "caremed_dev_session"

    SESSION_COOKIE_SECURE = False    
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    REMEMBER_COOKIE_DURATION    = timedelta(hours=8)
    REMEMBER_COOKIE_SECURE      = False
    REMEMBER_COOKIE_HTTPONLY    = True
    REMEMBER_COOKIE_SAMESITE    = "Lax"

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    MAIL_DEFAULT_SENDER = (
        os.environ.get("MAIL_SENDER_NAME", "CareMed Dev"),
        MAIL_USERNAME
    )

    MAIL_MAX_EMAILS = 5
    MAIL_TIMEOUT = 10

    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_SUPPRESS_SEND", "True").lower() in ("true", "1", "t")

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }