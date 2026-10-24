from datetime import datetime
from decimal import Decimal, InvalidOperation

from extensions import db


# Default business rules derived from the ATRIMS-CareMed thesis.
# Values can be changed by the Owner/Admin at /admin/settings without a code change
# (Non-Functional Requirement: Maintainability, Chapter III).
DEFAULTS = {
    "deposit_flat_amount": (
        "1500.00",
        "decimal",
        "Refundable deposit for delivery rentals (FR02 / RULE-03)",
    ),
    "late_fee_per_day": (
        "100.00",
        "decimal",
        "Late fee per rented unit per day overdue (RULE-09)",
    ),
    "damage_fee_minor_pct": (
        "25",
        "int",
        "Minor damage fee, percent of held deposit (RULE-10)",
    ),
    "damage_fee_major_pct": (
        "50",
        "int",
        "Major damage fee, percent of held deposit (RULE-10)",
    ),
    "default_reorder_level": (
        "5",
        "int",
        "Fallback reorder level for products without an explicit value (FR07)",
    ),
    "cutoff_days": (
        "5,20",
        "string",
        "Prime Gas supplier reconciliation cutoffs (day of month)",
    ),
}


class SystemSetting(db.Model):
    """Key/value store for business rules the owner must edit without code."""

    __tablename__ = "system_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    data_type = db.Column(db.String(16), nullable=False, default="string")
    description = db.Column(db.String(255), nullable=True)
    updated_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_python(self):
        if self.data_type == "int":
            try:
                return int(self.value)
            except (TypeError, ValueError):
                return 0
        if self.data_type == "decimal":
            try:
                return Decimal(str(self.value))
            except (InvalidOperation, TypeError, ValueError):
                return Decimal("0.00")
        if self.data_type == "bool":
            return str(self.value).lower() in ("1", "true", "yes", "on")
        return self.value

    @classmethod
    def get_row(cls, key):
        """Return the stored row, or a transient row carrying the default."""
        row = db.session.get(cls, key)
        if row is not None:
            return row
        default = DEFAULTS.get(key)
        if default is None:
            return None
        return cls(key=key, value=default[0], data_type=default[1], description=default[2])

    @classmethod
    def value_of(cls, key):
        row = cls.get_row(key)
        return row.as_python() if row else None

    @classmethod
    def set_value(cls, key, value, user_id=None):
        row = db.session.get(cls, key)
        default = DEFAULTS.get(key, ("", "string", None))
        if row is None:
            row = cls(
                key=key,
                data_type=default[1],
                description=default[2],
            )
            db.session.add(row)
        row.value = str(value)
        row.updated_by_id = user_id
        return row

    @classmethod
    def all_effective(cls):
        """Defaults overlaid with stored values, in a stable order."""
        stored = {row.key: row for row in cls.query.all()}
        result = {}
        for key, (value, data_type, description) in DEFAULTS.items():
            result[key] = stored.get(key) or cls(
                key=key, value=value, data_type=data_type, description=description
            )
        for key, row in stored.items():
            result.setdefault(key, row)
        return result
