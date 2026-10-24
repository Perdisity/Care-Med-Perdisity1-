from datetime import datetime

from extensions import db


class VoidRequest(db.Model):
    """Admin approval queue for void/cancel actions (Chapter IV, Table 15)."""

    __tablename__ = "void_requests"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transaction.id", ondelete="CASCADE"), nullable=False
    )
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    requested_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.String(255), nullable=True)

    transaction = db.relationship(
        "Transaction", backref=db.backref("void_requests", lazy="dynamic")
    )
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])


class StockAdjustment(db.Model):
    """Physical-count adjustment submitted by a custodian, approved by an Admin."""

    __tablename__ = "stock_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    system_qty = db.Column(db.Integer, nullable=False, default=0)
    counted_qty = db.Column(db.Integer, nullable=False)
    variance = db.Column(db.Integer, nullable=False, default=0)
    reason_code = db.Column(db.String(40), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    requested_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.String(255), nullable=True)

    product = db.relationship("Product", backref=db.backref("adjustments", lazy="dynamic"))
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])
