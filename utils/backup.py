import os
import subprocess
from datetime import datetime
from urllib.parse import urlparse
import shutil

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backups')
MAX_BACKUPS = 7

MYSQLDUMP_PATH = os.environ.get("MYSQLDUMP_PATH") or shutil.which("mysqldump") or r"C:\xampp\mysql\bin\mysqldump.exe"
MYSQL_PATH = os.environ.get("MYSQL_PATH") or shutil.which("mysql") or r"C:\xampp\mysql\bin\mysql.exe"


def is_sqlite_database():
    try:
        from extensions import db
        return db.engine.url.drivername.startswith("sqlite")
    except Exception:
        db_url = os.environ.get('DATABASE_URL', '')
        return db_url.startswith("sqlite") or not db_url


def get_db_credentials():
    db_url = os.environ.get('DATABASE_URL', '').strip()
    if not db_url:
        return None
    db_url = db_url.replace("mysql+pymysql://", "mysql://")

    try:
        parsed = urlparse(db_url)
        if not parsed.hostname or not parsed.path:
            return None

        # Production-grade root fallback: bypasses application user permissions and credential clashes
        root_password = os.environ.get('MYSQL_ROOT_PASSWORD', '')
        if not root_password and parsed.username == 'root':
            root_password = parsed.password or ''

        return {
            'user': 'root',
            'password': root_password,
            'host': parsed.hostname,
            'port': parsed.port or 3306,
            'dbname': parsed.path.lstrip('/')
        }
    except Exception as e:
        print(f"[Backup] DB Parse Error: {e}")
        return None


def with_app_context_if_needed(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            from flask import has_app_context
            if not has_app_context():
                from app import app
                with app.app_context():
                    return fn(*args, **kwargs)
        except Exception:
            pass
        return fn(*args, **kwargs)
    return wrapper


@with_app_context_if_needed
def create_backup(triggered_by='system'):
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"caremed_backup_{triggered_by}_{timestamp}.sql"
        filepath = os.path.join(BACKUP_DIR, filename)

        if is_sqlite_database():
            from extensions import db
            conn = db.engine.raw_connection()
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    for line in conn.iterdump():
                        f.write(f"{line}\n")
            finally:
                conn.close()

            if os.path.getsize(filepath) == 0:
                if os.path.exists(filepath):
                    os.remove(filepath)
                return False, "Backup file was empty"

            cleanup_old_backups()
            size_kb = round(os.path.getsize(filepath) / 1024, 2)
            print(f"[Backup] SQLite Backup Created: {filename} ({size_kb} KB) by {triggered_by}")
            return True, filename

        creds = get_db_credentials()
        if not creds:
            return False, "Could not parse database credentials"

        if not os.path.exists(MYSQLDUMP_PATH):
            return False, f"mysqldump not found at: {MYSQLDUMP_PATH}"

        env = os.environ.copy()
        env['MYSQL_PWD'] = creds['password']

        command = [
            MYSQLDUMP_PATH,
            f"--user={creds['user']}",
            f"--host={creds['host']}",
            f"--port={str(creds['port'])}",
            '--single-transaction',
            '--routines',
            '--triggers',
            '--default-character-set=utf8mb4',
            creds['dbname']
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            env=env
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()[:500]
            return False, f"mysqldump error: {error_msg}"

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result.stdout)

        if os.path.getsize(filepath) == 0:
            os.remove(filepath)
            return False, "Backup file was empty"

        cleanup_old_backups()

        size_kb = round(os.path.getsize(filepath) / 1024, 2)
        print(f"[Backup] MySQL Backup Created: {filename} ({size_kb} KB) by {triggered_by}")
        return True, filename

    except subprocess.TimeoutExpired:
        return False, "Backup timed out after 5 minutes"

    except FileNotFoundError:
        return False, f"mysqldump executable not found: {MYSQLDUMP_PATH}"

    except PermissionError:
        return False, "Permission denied while creating backup"

    except Exception as e:
        return False, f"Unexpected backup error: {str(e)}"


@with_app_context_if_needed
def restore_backup(filename, triggered_by='admin'):
    """
    Restores the database from a specified backup file.
    Always creates an automatic pre-restore safety backup first.
    Returns (success: bool, message: str).
    """
    if not filename or not filename.endswith('.sql') or '..' in filename or '/' in filename or '\\' in filename:
        return False, f"Invalid backup filename: {filename}"

    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(filepath):
        return False, f"Backup file not found: {filename}"

    # Step 1: Create automatic pre-restore safety backup
    safety_ok, safety_result = create_backup(triggered_by='pre_restore_safety')
    if not safety_ok:
        return False, f"Restore aborted: pre-restore safety backup failed ({safety_result})"

    # Step 2: Perform database restore
    try:
        if is_sqlite_database():
            from extensions import db
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = OFF;")
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table}";')

                cursor.execute("SELECT name FROM sqlite_master WHERE type='view';")
                views = [row[0] for row in cursor.fetchall()]
                for view in views:
                    cursor.execute(f'DROP VIEW IF EXISTS "{view}";')
                conn.commit()

                with open(filepath, 'r', encoding='utf-8') as f:
                    sql_script = f.read()

                cursor.executescript(sql_script)
                cursor.execute("PRAGMA foreign_keys = ON;")
                conn.commit()
            finally:
                cursor.close()
                conn.close()

            print(f"[Backup] Restore completed from {filename} with safety backup {safety_result}")
            return True, f"Database restored successfully from '{filename}'. Pre-restore safety backup saved as '{safety_result}'."

        # MySQL Restore
        creds = get_db_credentials()
        if not creds:
            return False, "Could not parse database credentials for MySQL restore"

        if not os.path.exists(MYSQL_PATH):
            return False, f"mysql executable not found at: {MYSQL_PATH}"

        env = os.environ.copy()
        env['MYSQL_PWD'] = creds['password']

        command = [
            MYSQL_PATH,
            f"--user={creds['user']}",
            f"--host={creds['host']}",
            f"--port={str(creds['port'])}",
            '--default-character-set=utf8mb4',
            creds['dbname']
        ]

        with open(filepath, 'r', encoding='utf-8') as f:
            result = subprocess.run(
                command,
                stdin=f,
                capture_output=True,
                text=True,
                timeout=300,
                env=env
            )

        if result.returncode != 0:
            error_msg = result.stderr.strip()[:500]
            return False, f"mysql restore error: {error_msg}"

        print(f"[Backup] MySQL Restore completed from {filename} with safety backup {safety_result}")
        return True, f"Database restored successfully from '{filename}'. Pre-restore safety backup saved as '{safety_result}'."

    except Exception as e:
        return False, f"Restore failed with error: {str(e)}"


def cleanup_old_backups():
    try:
        if not os.path.exists(BACKUP_DIR):
            return

        backups = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.endswith('.sql')],
            key=lambda x: os.path.getctime(os.path.join(BACKUP_DIR, x))
        )

        while len(backups) > MAX_BACKUPS:
            oldest = backups.pop(0)
            old_path = os.path.join(BACKUP_DIR, oldest)
            if os.path.exists(old_path):
                os.remove(old_path)
                print(f"[Backup] Deleted old backup: {oldest}")

    except Exception as e:
        print(f"[Backup] Cleanup error: {e}")


def get_all_backups():
    try:
        if not os.path.exists(BACKUP_DIR):
            return []

        backups = []

        for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if filename.endswith('.sql'):
                filepath = os.path.join(BACKUP_DIR, filename)

                if not os.path.isfile(filepath):
                    continue

                size = os.path.getsize(filepath)
                created = datetime.fromtimestamp(os.path.getctime(filepath))
                if '_pre_restore_safety_' in filename:
                    triggered_by = 'safety'
                elif '_admin_' in filename:
                    triggered_by = 'admin'
                else:
                    triggered_by = 'system'

                backups.append({
                    'filename': filename,
                    'size_kb': round(size / 1024, 2),
                    'created_at': created,
                    'triggered_by': triggered_by
                })

        return backups

    except Exception as e:
        print(f"[Backup] List error: {e}")
        return []


def auto_backup():
    print(f"[Backup] Auto backup starting at {datetime.utcnow()}")
    success, result = create_backup(triggered_by='system')

    if success:
        print(f"[Backup] Auto backup successful: {result}")
    else:
        print(f"[Backup] Auto backup FAILED: {result}")
        try:
            from flask import current_app
            from extensions import mail
            from flask_mail import Message

            admin_email = current_app.config.get('MAIL_USERNAME')
            if admin_email:
                msg = Message(
                    subject="[CareMed] Auto Backup FAILED",
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                    recipients=[admin_email]
                )
                msg.body = f"""
CareMed Auto Backup Failed
==========================
Time  : {datetime.utcnow().strftime('%B %d, %Y %I:%M %p')} UTC
Reason: {result}

Please check your server and create a manual backup immediately.
                """
                mail.send(msg)
        except Exception as mail_err:
            print(f"[Backup] Failed to send backup alert: {mail_err}")