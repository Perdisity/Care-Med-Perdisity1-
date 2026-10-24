from extensions import db
from datetime import datetime, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta

class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    asset_tag = db.Column(db.String(20), nullable=True, unique=True)
    equipment_type = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    size = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True) 
    stock = db.Column(db.Integer, default=0)
    # Per-product reorder level (FR07 / RULE-05). Falls back to the system default.
    reorder_level = db.Column(db.Integer, nullable=False, default=5)
    # Units returned damaged and therefore not available for rent (RULE-10).
    damaged_stock = db.Column(db.Integer, nullable=False, default=0)
    
    transaction_type = db.Column(db.String(20), nullable=True, default="Sale")
    cost_price = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    sale_price = db.Column(db.Numeric(10, 2), nullable=True)
    rent_price = db.Column(db.Numeric(10, 2), nullable=True)
    rent_period = db.Column(db.String(20), nullable=True, default="Monthly")
    
    condition = db.Column(db.String(50), nullable=True, default="Brand New")
    image = db.Column(db.String(255))
    status = db.Column(db.String(50), default="Available")
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    is_refillable = db.Column(db.Boolean, default=False, index=True) 
    category = db.Column(db.String(50), nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    purchases = db.relationship("Purchase", back_populates="product", passive_deletes=True)
    rentals = db.relationship("Rental", back_populates="product", passive_deletes=True)
    tank_status = db.relationship("TankStatus", back_populates="product", uselist=False, cascade="all, delete-orphan")
    inventory_logs = db.relationship("InventoryLog", back_populates="product", passive_deletes=True)
    
class TankStatus(db.Model):
    __tablename__ = "tank_status"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False)
    
    total_owned = db.Column(db.Integer, default=0)
    rented_out = db.Column(db.Integer, default=0) 
    full_in_stock = db.Column(db.Integer, default=0) 
    empty_in_stock = db.Column(db.Integer, default=0) 
    damaged_in_stock = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", back_populates="tank_status")

    @property
    def total_available(self):
        return (self.full_in_stock or 0) + (self.empty_in_stock or 0)

class RentalTankLog(db.Model):
    __tablename__ = "rental_tank_log"

    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey("rental.id", ondelete="CASCADE"), nullable=False)
    tank_id = db.Column(db.Integer, db.ForeignKey("rental_tank.id", ondelete="SET NULL"), nullable=True)
    
    old_serial_number = db.Column(db.String(100), nullable=True)
    new_serial_number = db.Column(db.String(100), nullable=False)
    
    reason = db.Column(db.String(255), nullable=True)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    rental = db.relationship("Rental", backref=db.backref("tank_logs", cascade="all, delete-orphan"))
    changed_by = db.relationship("User")
    
class Purchase(db.Model):
    __tablename__ = "purchase"

    id = db.Column(db.Integer, primary_key=True)

    transaction_id = db.Column(db.Integer,db.ForeignKey("transaction.id"),nullable=False)

    product_id = db.Column(db.Integer,db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id", ondelete="SET NULL"), nullable=True)

    product_name = db.Column(db.String(100), nullable=False)
    product_type = db.Column(db.String(100), nullable=True)
    product_asset_tag = db.Column(db.String(20), nullable=True)
    product_condition = db.Column(db.String(50), nullable=True)

    product_description = db.Column(db.Text, nullable=True)
    product_image = db.Column(db.String(255), nullable=True)
    product_category = db.Column(db.String(50), nullable=True)

    product_cost_price = db.Column(db.Numeric(10, 2), nullable=True)
    product_sale_price = db.Column(db.Numeric(10, 2), nullable=True)
    product_rent_price = db.Column(db.Numeric(10, 2), nullable=True)
    product_rent_period = db.Column(db.String(20), nullable=True)

    quantity = db.Column(db.Integer, nullable=False)

    unit_price = db.Column(db.Numeric(10, 2))
    total_price = db.Column(db.Numeric(10, 2))

    warranty_or_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    transaction = db.relationship("Transaction", back_populates="purchases")

    product = db.relationship("Product", back_populates="purchases")

    customer = db.relationship("Customer", back_populates="purchases")

class Transaction(db.Model):
    __tablename__ = "transaction"

    id = db.Column(db.Integer, primary_key=True)
    reference_no = db.Column(db.String(36), unique=True, nullable=False, index=True)
    
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_name = db.Column(db.String(255))
    processed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    transaction_type = db.Column(db.String(20), nullable=False, index=True)
    
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    voucher_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    amount_paid = db.Column(db.Numeric(10, 2), default=0.00)
    balance_due = db.Column(db.Numeric(10, 2), default=0.00)
    
    payment_method = db.Column(db.String(50), nullable=True)
    payment_status = db.Column(db.String(50), default="Unpaid") 
    status = db.Column(db.String(20), default="Open", index=True)
    
    cancellation_reason = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=True)
    refill_cost_per_unit = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    serial_numbers = db.Column(db.Text, nullable=True)
    walk_in_tank_size = db.Column(db.String(50), nullable=True)

    has_initial_fill = db.Column(db.Boolean, default=False)
    initial_fill_cost = db.Column(db.Numeric(10, 2), default=0.00)

    customer = db.relationship("Customer", back_populates="transactions")
    admin = db.relationship("User", backref="processed_transactions")
    product = db.relationship("Product", backref="product_refills")
    purchases = db.relationship("Purchase", back_populates="transaction", cascade="all, delete-orphan")
    rentals = db.relationship("Rental", back_populates="transaction", cascade="all, delete-orphan")
    
    payments = db.relationship("Payment", back_populates="transaction", cascade="all, delete-orphan")
    payment_proof = db.relationship("PaymentProof", backref="transaction", uselist=False, cascade="all, delete-orphan")
    
    deposit_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    distance_km = db.Column(db.Numeric(6, 2), nullable=True)
    deposit_rule = db.Column(db.String(50), nullable=True)
    
    fulfillment_type = db.Column(db.String(20), default="Walk-in") 
    delivery_status = db.Column(db.String(20), default="N/A") 
    tracking_status = db.Column(db.String(20), default="SUBMITTED")
    delivery_address = db.Column(db.Text, nullable=True)
    landmark = db.Column(db.String(255), nullable=True) 
    
    @property
    def computed_status(self):
        """Computes status accurately based on rental monthly invoices and payment status."""
        from datetime import date
        current_date = date.today()
        
        is_rental = self.transaction_type == 'Rental'
        
        if is_rental and self.rentals:
            for rental in self.rentals:
                if rental.expected_return_date and rental.expected_return_date < current_date and rental.status == 'Active':
                    return 'overdue_return'

            has_overdue_invoice = False
            has_partial_invoice = False
            has_unpaid_invoice = False
            
            for rental in self.rentals:
                for inv in rental.invoices:
                    inv_status = (inv.status or '').lower()
                    if inv_status != 'paid':
                        period_end = getattr(inv, 'service_period_end', None)
                        if period_end and period_end < current_date:
                            if inv_status in ['unpaid', 'pending', '']:
                                has_overdue_invoice = True
                            elif inv_status in ['partial', 'partially paid']:
                                has_partial_invoice = True
                        else:
                            if inv_status in ['unpaid', 'pending', '']:
                                has_unpaid_invoice = True
                            elif inv_status in ['partial', 'partially paid']:
                                has_partial_invoice = True

            if has_overdue_invoice:
                return 'overdue_payment'
            if has_partial_invoice:
                return 'partial'
            if has_unpaid_invoice:
                return 'unpaid'

        has_balance = self.balance_due is not None and self.balance_due > 0

        if has_balance and getattr(self, 'due_date', None) and self.due_date < current_date:
            return 'overdue_payment'

        if self.status == 'expiring':
            return 'expiring'

        if self.status == 'submitted' or self.tracking_status == 'SUBMITTED':
            return 'submitted'

        if has_balance and self.amount_paid and self.amount_paid > 0:
            return 'partial'

        if has_balance and (not self.amount_paid or self.amount_paid == 0):
            return 'unpaid'

        return self.status.lower() if self.status else 'unknown'
    
    @property
    def total_cost(self):
        if self.transaction_type == "Refill" and self.quantity and self.refill_cost_per_unit:
            return Decimal(str(self.quantity)) * Decimal(str(self.refill_cost_per_unit))
        return Decimal("0.00")

    @property
    def net_profit(self):
        if self.transaction_type == "Refill":
            revenue = Decimal(str(self.total_amount or 0))
            return revenue - self.total_cost
        return Decimal("0.00")

    @property
    def gross_amount(self):
        return (self.total_amount or Decimal("0.00")) + (self.voucher_amount or Decimal("0.00"))

    @property
    def display_amount(self):
        return self.total_amount or Decimal("0.00")

    @property
    def display_date(self):
        if not self.created_at:
            return "N/A"
        if self.transaction_type == "Refill":
            return self.created_at.strftime('%b %d, %Y %I:%M %p')
        return self.created_at.strftime('%b %d, %Y')

    @property
    def description(self):
        if self.transaction_type == "Sale":
            return "Product Purchase"
        elif self.transaction_type == "Rental":
            return "Rental Transaction"
        elif self.transaction_type == "Refill":
            tank_desc = f" ({self.walk_in_tank_size})" if self.walk_in_tank_size else ""
            prod_name = self.product.name if self.product else "Tank Refill"
            qty = self.quantity or 1
            return f"Refill: {prod_name}{tank_desc} x{qty}"
        return "Transaction"
    
    @property
    def tracking_stage(self):
        if self.status and self.status.lower() == "cancelled":
            return "CANCELLED"
        if self.tracking_status:
            return self.tracking_status.upper()
        return "SUBMITTED"

    @property
    def status_badge(self):
        if self.transaction_type == "Refill":
            return "badge-success"
        return "badge-success" if self.status == "Closed" else "badge-warning"
    
    @property
    def initial_fill_paid(self):
        return sum(
            (Decimal(str(p.amount)) for p in self.payments if p.invoice_id is None and p.status == "Completed"),
            Decimal("0.00")
        )

    @property
    def initial_fill_balance(self):
        if not self.initial_fill_cost:
            return Decimal("0.00")
        return max(Decimal(str(self.initial_fill_cost)) - self.initial_fill_paid, Decimal("0.00"))
    
    @property
    def subtotal(self):
        if self.transaction_type == "Sale":
            return sum(
                (Decimal(str(p.unit_price or 0)) * Decimal(str(p.quantity or 0)) for p in self.purchases),
                Decimal("0.00")
            )
        elif self.transaction_type == "Rental":
            return sum(
                (Decimal(str(r.monthly_rate or 0)) * Decimal(str(r.quantity or 0)) for r in self.rentals),
                Decimal("0.00")
            )
        elif self.transaction_type == "Refill":
            return Decimal(str(self.quantity or 1)) * Decimal(str(self.refill_cost_per_unit or 0))
        return Decimal("0.00")

    def update_totals(self):
            delivery_fee = Decimal(str(self.delivery_fee or 0))
            voucher_amount = Decimal(str(self.voucher_amount or 0))
            initial_fill = Decimal(str(self.initial_fill_cost or 0))
            deposit_amt = Decimal(str(self.deposit_amount or 0))

            if self.transaction_type == "Refill":
                raw_cost = Decimal(str(self.quantity or 1)) * Decimal(str(self.refill_cost_per_unit or 0))
                self.total_amount = max(raw_cost + delivery_fee - voucher_amount, Decimal("0.00"))

                self.balance_due = Decimal("0.00")
                self.payment_status = "Fully Paid"
                self.status = "Closed"
                return

            total_paid = sum(
                (Decimal(str(p.amount)) for p in self.payments if p.status == "Completed"),
                Decimal("0.00")
            )
            self.amount_paid = total_paid

            if self.transaction_type == "Rental":
                total_invoice_sum = Decimal("0.00")
                for rental in self.rentals:
                    for inv in rental.invoices:
                        if getattr(inv, 'status', None) == 'Cancelled':
                            continue
                        total_invoice_sum += Decimal(str(inv.amount_due or 0)) + Decimal(str(inv.late_fee or 0))

                self.total_amount = max(total_invoice_sum + delivery_fee + initial_fill - voucher_amount, Decimal("0.00"))

            
                gross_liability = self.total_amount + deposit_amt
                self.balance_due = max(Decimal("0.00"), gross_liability - self.amount_paid)
                
            elif self.transaction_type == "Sale":
                subtotal = sum(
                    (Decimal(str(p.total_price or (Decimal(str(p.unit_price or 0)) * Decimal(str(p.quantity or 0))))) for p in self.purchases),
                    Decimal("0.00")
                )
                
                self.total_amount = max(subtotal + delivery_fee - voucher_amount, Decimal("0.00"))

                gross_liability = self.total_amount + deposit_amt
                self.balance_due = max(Decimal("0.00"), gross_liability - total_paid)
                
            current_total = Decimal(str(self.total_amount or 0))

            if total_paid <= 0:
                self.payment_status = "Unpaid"
            elif total_paid < (current_total + deposit_amt):
                self.payment_status = "Partially Paid"
            else:
                self.payment_status = "Fully Paid"

            if self.payment_status == "Fully Paid":
                if self.transaction_type == "Sale":
                    if self.fulfillment_type == "Delivery":
                        if (self.delivery_status == "Delivered" or self.tracking_status == "DELIVERED"):
                            self.status = "Closed"
                            self.delivery_status = "Delivered"  
                        else:  
                            if self.delivery_status in ["Walk-in", "N/A"]:
                                self.status = "Closed"

                elif self.transaction_type == "Rental":
                    if self.rentals and all(r.status == "Returned" for r in self.rentals):
                        all_invoices_paid = all(
                            all(inv.status == "Paid" for inv in r.invoices) 
                            for r in self.rentals
                        )
                        if all_invoices_paid:
                            self.status = "Closed"
            else:
                if self.status == "Closed":
                    self.status = "Open"  
                                                    
class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id", ondelete="CASCADE"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("rental_invoice.id"), nullable=True)

    payment_type = db.Column(db.String(50), default="Rental Invoice", nullable=False, index=True)
    
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False) 
    reference_number = db.Column(db.String(100), nullable=True, unique=True, index=True)
    receipt_image_path = db.Column(db.String(255))
    
    status = db.Column(db.String(20), default="Pending")
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship("Transaction", back_populates="payments")
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])
    rental_invoice = db.relationship("RentalInvoice", back_populates="payments")

class PaymentProof(db.Model):
    __tablename__ = "payment_proof"
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=True)
    reference_number = db.Column(db.String(100), nullable=False)
    proof_image = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

class CustomerDeposit(db.Model):
    __tablename__ = "customer_deposit"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True)
    
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    status = db.Column(db.String(20), default="Held", index=True) # Held, Refunded, Applied
    notes = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("Customer", backref=db.backref("deposits", cascade="all, delete-orphan"))
    transaction = db.relationship("Transaction", backref=db.backref("customer_deposits", cascade="all, delete-orphan"))
    
class Rental(db.Model):
    __tablename__ = "rental"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    
    start_date = db.Column(db.Date, nullable=False)
    expected_return_date = db.Column(db.Date, nullable=False) 
    actual_return_date = db.Column(db.Date, nullable=True) 

    monthly_rate = db.Column(db.Numeric(10, 2))
    deposit_amount = db.Column(db.Numeric(10, 2))
    deposit_status = db.Column(db.String(20), default="Held") 
    late_fees_incurred = db.Column(db.Numeric(10, 2), default=0.00)

    quantity = db.Column(db.Integer, nullable=False)
    quantity_returned = db.Column(db.Integer, nullable=False, default=0)
    
    status = db.Column(db.String(50), default="Active", index=True)
    is_open_duration = db.Column(db.Boolean, default=False, nullable=False)
    return_condition_notes = db.Column(db.Text)
    # RULE-10: condition recorded at return and the fee assessed against the deposit.
    return_condition = db.Column(db.String(30), nullable=True)
    damage_fee = db.Column(db.Numeric(10, 2), default=0.00)
    
    is_deposit_refunded = db.Column(db.Boolean, default=False)
    delivery_fee = db.Column(db.Numeric(10, 2), default=0.00)
    return_condition_img = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship("Transaction", back_populates="rentals")
    product = db.relationship("Product", back_populates="rentals")
    customer = db.relationship("Customer", back_populates="rentals")
    invoices = db.relationship("RentalInvoice", backref="rental", cascade="all, delete-orphan", lazy=True)

    @property
    def remaining_to_return(self):
        return max(0, self.quantity - self.quantity_returned)

    def get_latest_invoice(self):
        """Returns the invoice with the furthest service period end date."""
        if not self.invoices:
            return None
        return max(self.invoices, key=lambda inv: inv.service_period_end)

    def generate_next_monthly_invoice(self):
        """Generates the subsequent monthly billing cycle invoice for open rentals."""
        latest = self.get_latest_invoice()
        if not latest:
            next_start = self.start_date
        else:
            next_start = latest.service_period_end

        next_end = next_start + relativedelta(months=1)
        item_monthly_total = (self.monthly_rate or Decimal("0.00")) * self.quantity

        new_invoice = RentalInvoice(
            rental_id=self.id,
            service_period_start=next_start,
            service_period_end=next_end,
            amount_due=item_monthly_total,
            status="Unpaid"
        )
        db.session.add(new_invoice)

        if next_end > self.expected_return_date:
            self.expected_return_date = next_end
            
        return new_invoice

    def generate_monthly_invoices(self):
        current_period_start = self.start_date
        while current_period_start < self.expected_return_date:
            next_period_start = current_period_start + relativedelta(months=1)
            actual_period_end = next_period_start if next_period_start < self.expected_return_date else self.expected_return_date

            item_monthly_total = (self.monthly_rate or Decimal("0.00")) * self.quantity

            new_invoice = RentalInvoice(
                rental_id=self.id,
                service_period_start=current_period_start,
                service_period_end=actual_period_end,
                amount_due=item_monthly_total,
                status="Unpaid"
            )
            db.session.add(new_invoice)
            current_period_start = next_period_start
            
    def process_rental_extension(self, extension_days):
        """
        Extends an active rental period by a specified number of days and updates the service period end.
        """
        if self.status != 'Active':
            return False, "Rental is not active or does not exist."
        
        latest_invoice = self.get_latest_invoice()
        if latest_invoice:
            if isinstance(latest_invoice.service_period_end, str):
                latest_invoice.service_period_end = datetime.strptime(latest_invoice.service_period_end, '%Y-%m-%d').date()
            latest_invoice.service_period_end += timedelta(days=extension_days)
            
            if latest_invoice.service_period_end > self.expected_return_date:
                self.expected_return_date = latest_invoice.service_period_end
                
            db.session.commit()
            return True, latest_invoice.service_period_end.isoformat()
        
        return False, "No associated invoice found for this rental."
    
class RentalTank(db.Model):
    __tablename__ = "rental_tank"

    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rental.id"),
        nullable=False
    )
    serial_number = db.Column(db.String(100), nullable=False)
    status = db.Column(
        db.String(20),
        default="Active"
    )

    rental = db.relationship(
        "Rental",
        backref=db.backref(
            "tanks",
            cascade="all, delete-orphan"
        )
    )
    
class RentalInvoice(db.Model):
    __tablename__ = "rental_invoice"
    
    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey("rental.id"), nullable=False)
    
    service_period_start = db.Column(db.Date, nullable=False)
    service_period_end = db.Column(db.Date, nullable=False)
    
    amount_due = db.Column(db.Numeric(10, 2), nullable=False)
    late_fee = db.Column(db.Numeric(10, 2), default=0.00)
    status = db.Column(db.String(20), default="Unpaid") 
    
    payments = db.relationship("Payment", back_populates="rental_invoice", lazy=True)

    @property
    def total_invoice_value(self):
        return Decimal(str(self.amount_due)) + Decimal(str(self.late_fee or 0))

    @property
    def amount_paid(self):
        return sum(
            (Decimal(str(p.amount)) for p in self.payments if p.status == "Completed"),
            Decimal("0.00")
        )

    @property
    def remaining_balance(self):
        return max(self.total_invoice_value - self.amount_paid, Decimal("0.00"))
    
    
class InventoryLog(db.Model):
    __tablename__ = "inventory_logs"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id", ondelete="SET NULL"), nullable=True, index=True)
    reference_no = db.Column(db.String(40), nullable=True, index=True)
    reason_code = db.Column(db.String(30), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=True)
    balance_after = db.Column(db.Integer, nullable=True)
    note = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    product = db.relationship("Product", back_populates="inventory_logs")
    user = db.relationship("User", backref=db.backref("inventory_logs", lazy="dynamic"))
    transaction = db.relationship("Transaction", backref=db.backref("inventory_logs", lazy="dynamic"))
    
    
class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    expense_title = db.Column(db.String(120), nullable=True) 
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    # FR06: units converted from empty to full in this supplier batch.
    refill_quantity = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(255))
    attachment_path = db.Column(db.String(255)) 
    
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"), nullable=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    date_incurred = db.Column(db.Date, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
    product = db.relationship("Product", foreign_keys=[product_id], backref=db.backref("expenses", lazy="dynamic"))
    
    
class Cart(db.Model):
    __tablename__ = "cart"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")
    user = db.relationship("User", backref=db.backref("cart", uselist=False))

class CartItem(db.Model):
    __tablename__ = "cart_item"
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    
    quantity = db.Column(db.Integer, default=1)
    item_type = db.Column(db.String(20), nullable=False) 
    
    rental_start_date = db.Column(db.Date, nullable=True)
    rental_duration = db.Column(db.Integer, nullable=True)
    price_at_addition = db.Column(db.Numeric(10, 2))

    cart = db.relationship("Cart", back_populates="items")
    product = db.relationship("Product")
    
class ProductReview(db.Model):
    __tablename__ = 'product_reviews'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('reviews', lazy=True, cascade="all, delete-orphan"))
    product = db.relationship('Product', backref=db.backref('reviews', lazy=True, cascade="all, delete-orphan"))
    
    def __repr__(self):
        return f"<ProductReview User {self.user_id} -> Product {self.product_id}: {self.rating} Stars>"