import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from extensions import db


# Default business rules derived from the ATRIMS-CareMed thesis.
# Values can be changed by the Owner/Admin at /admin/settings without a code change
# (Non-Functional Requirement: Maintainability, Chapter III).
DEFAULTS = {
    "deposit_flat_amount": (
        "1500.00",
        "decimal",
        "Fallback refundable deposit when no distance tier matches (FR02 / RULE-03)",
    ),
    "deposit_distance_tiers": (
        "3:500,6:1000,*:1500",
        "string",
        "Distance-based delivery deposit tiers: max_km:amount, * for fallback (FR02 / RULE-03)",
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


def _format_km(value):
    """Render a Decimal distance without unnecessary trailing zeroes."""
    return format(Decimal(value).normalize(), "f")


def parse_deposit_tiers(raw):
    """Parse ``3:500, 6:1000, *:1500`` into ordered deposit tiers.

    Each tier is a dict with ``max_km`` (Decimal or None for the fallback),
    ``amount`` (Decimal) and a human-readable ``label``. Invalid input raises
    ``ValueError`` so the settings screen can explain the problem.
    """
    if raw is None:
        return []

    tokens = raw if isinstance(raw, (list, tuple)) else re.split(r"[\n,;]+", str(raw))
    tiers = []
    seen = set()

    for token in tokens:
        token = str(token).strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"'{token}' is not a tier. Use max_km:amount, for example 3:500.")

        max_raw, amount_raw = token.split(":", 1)
        max_raw = max_raw.strip().lower()
        amount_raw = amount_raw.strip()
        if not amount_raw:
            raise ValueError(f"'{token}' is missing a deposit amount.")

        try:
            amount = Decimal(amount_raw)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"'{amount_raw}' is not a valid deposit amount.")
        if not amount.is_finite() or amount < 0:
            raise ValueError("Deposit amounts must be zero or positive.")
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if max_raw in ("*", "all", "fallback", "default"):
            max_km = None
        else:
            try:
                max_km = Decimal(max_raw)
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f"'{max_raw}' is not a valid distance.")
            if not max_km.is_finite() or max_km <= 0:
                raise ValueError("Tier distances must be greater than zero.")

        if max_km in seen:
            label = "fallback" if max_km is None else f"{_format_km(max_km)} km"
            raise ValueError(f"Duplicate deposit tier for {label}.")
        seen.add(max_km)
        tiers.append({"max_km": max_km, "amount": amount})

    tiers.sort(
        key=lambda tier: (
            tier["max_km"] is None,
            tier["max_km"] if tier["max_km"] is not None else Decimal("0"),
        )
    )

    previous_numeric = None
    for tier in tiers:
        if tier["max_km"] is None:
            tier["label"] = (
                f"Above {_format_km(previous_numeric)} km"
                if previous_numeric is not None
                else "Flat delivery deposit"
            )
        else:
            if previous_numeric is None:
                tier["label"] = f"Up to {_format_km(tier['max_km'])} km"
            else:
                tier["label"] = (
                    f"{_format_km(previous_numeric)}–{_format_km(tier['max_km'])} km"
                )
            previous_numeric = tier["max_km"]

    return tiers


def format_deposit_tiers(tiers):
    """Serialise parsed tiers back into the compact settings format."""
    parts = []
    for tier in tiers:
        max_text = "*" if tier["max_km"] is None else _format_km(tier["max_km"])
        parts.append(f"{max_text}:{tier['amount']:.2f}")
    return ", ".join(parts)


def resolve_delivery_deposit(distance_km, tiers=None, fallback_amount=None):
    """Return ``(amount, rule_label)`` for a delivery distance.

    The fallback amount is only used when the tiers are empty or when no
    fallback tier is configured and the distance exceeds the final tier.
    """
    if distance_km is None:
        return Decimal("0.00"), None

    try:
        distance = Decimal(str(distance_km))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00"), None
    if not distance.is_finite() or distance <= 0:
        return Decimal("0.00"), None

    if tiers is None:
        try:
            tiers = parse_deposit_tiers(SystemSetting.value_of("deposit_distance_tiers"))
        except ValueError:
            tiers = []
    tiers = tiers or []

    for tier in tiers:
        if tier["max_km"] is not None and distance <= tier["max_km"]:
            return (
                tier["amount"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                tier["label"],
            )

    for tier in tiers:
        if tier["max_km"] is None:
            return (
                tier["amount"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                tier["label"],
            )

    if fallback_amount is None:
        fallback_amount = SystemSetting.value_of("deposit_flat_amount") or "0"
    try:
        fallback = Decimal(str(fallback_amount))
    except (InvalidOperation, TypeError, ValueError):
        fallback = Decimal("0.00")
    if not fallback.is_finite() or fallback < 0:
        fallback = Decimal("0.00")

    return (
        fallback.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "Flat delivery deposit",
    )


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
