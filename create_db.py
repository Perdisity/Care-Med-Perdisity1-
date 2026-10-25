"""
create_db.py — One-shot schema initialiser for Docker fresh installs.

Called by entrypoint.sh when no 'alembic_version' table is found.
Creates all SQLAlchemy-mapped tables and seeds the mandatory system
settings rows (from DEFAULTS in models/settings.py) so the app
starts cleanly on a brand-new volume.

This script is intentionally NOT called during normal development;
the local SQLite flow continues to rely on `flask db upgrade` inside
the developer shell.
"""

from app import app
from extensions import db

# Import every model so SQLAlchemy's metadata is fully populated
# before we call create_all().
import models.users          # noqa: F401 — User, SecurityLog, BlockedIP
import models.customer       # noqa: F401 — Customer
import models.product        # noqa: F401 — Product, Purchase, Rental, InventoryLog
import models.operations     # noqa: F401 — StockAdjustment, VoidRequest
import models.settings       # noqa: F401 — SystemSetting


def main() -> None:
    with app.app_context():
        print("[create_db] Running db.create_all() ...")
        db.create_all()
        print("[create_db] All tables created successfully.")

        # Seed default SystemSetting rows if the table is empty.
        # Uses the DEFAULTS dict and set_value() that already exist in the model.
        from models.settings import SystemSetting, DEFAULTS
        if SystemSetting.query.count() == 0:
            print("[create_db] Seeding default SystemSetting rows ...")
            for key, (value, _data_type, _desc) in DEFAULTS.items():
                SystemSetting.set_value(key, value)
            db.session.commit()
            print(f"[create_db] {len(DEFAULTS)} SystemSetting defaults committed.")
        else:
            print("[create_db] SystemSetting rows already present — skipping seed.")


if __name__ == "__main__":
    main()
