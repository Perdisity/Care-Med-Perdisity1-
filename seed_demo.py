"""
seed_demo.py — Populates the fresh DB with realistic demo data for the defense.

Creates:
  • 3 Products  (Hospital Bed, Wheelchair, Oxygen Concentrator)
  • 3 Customers
  • 3 Transactions (1 Sale closed/paid, 1 Rental active, 1 Rental returned)
  • Inventory logs, rental invoices, payments
  • 3 Expenses
  • 3 Stock-adjustment records (pending review)

Safe to re-run — skips records that already exist.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta

from app import app
from extensions import db, passhasher
from models.users import User
from models.customer import Customer
from models.product import (
    Product, Transaction, Purchase, Rental,
    RentalInvoice, Payment, InventoryLog, Expense,
)
from models.operations import StockAdjustment
from models.settings import SystemSetting, DEFAULTS


# ── helpers ──────────────────────────────────────────────────────────────────

def ref():
    return str(uuid.uuid4())[:8].upper()


def today():
    return date.today()


def dt(d):
    return datetime.combine(d, datetime.min.time())


# ─────────────────────────────────────────────────────────────────────────────

def seed_settings():
    if SystemSetting.query.count() == 0:
        for key, (value, _dt, _desc) in DEFAULTS.items():
            SystemSetting.set_value(key, value)
        db.session.commit()
        print("[seed] SystemSetting defaults committed.")


def seed_products():
    specs = [
        dict(
            asset_tag="HB-001",
            equipment_type="Hospital Bed",
            name="Semi-Electric Hospital Bed",
            category="Hospital Bed",
            description="Semi-electric hospital bed with side rails and adjustable height. Suitable for home care and clinical use.",
            stock=8,
            reorder_level=3,
            transaction_type="Both",
            cost_price=Decimal("12000.00"),
            sale_price=Decimal("18500.00"),
            rent_price=Decimal("1800.00"),
            rent_period="Monthly",
            condition="Brand New",
            is_active=True,
        ),
        dict(
            asset_tag="WC-001",
            equipment_type="Wheelchair",
            name="Standard Manual Wheelchair",
            category="Wheelchairs & Mobility",
            description="Lightweight foldable manual wheelchair with padded armrests and footrests. Ideal for daily mobility.",
            stock=12,
            reorder_level=4,
            transaction_type="Both",
            cost_price=Decimal("3500.00"),
            sale_price=Decimal("5800.00"),
            rent_price=Decimal("600.00"),
            rent_period="Monthly",
            condition="Brand New",
            is_active=True,
        ),
        dict(
            asset_tag="OC-001",
            equipment_type="Oxygen Concentrator",
            name="5L Oxygen Concentrator",
            category="Oxygen Equipment",
            description="5-liter per minute continuous flow oxygen concentrator. Quiet operation, suitable for home oxygen therapy.",
            stock=5,
            reorder_level=2,
            transaction_type="Rental",
            cost_price=Decimal("22000.00"),
            sale_price=None,
            rent_price=Decimal("2500.00"),
            rent_period="Monthly",
            condition="Brand New",
            is_active=True,
        ),
    ]

    products = []
    for s in specs:
        existing = Product.query.filter_by(asset_tag=s["asset_tag"]).first()
        if existing:
            print(f"[seed] Product already exists: {s['name']}")
            products.append(existing)
            continue
        p = Product(**s)
        db.session.add(p)
        db.session.flush()
        print(f"[seed] Created product: {s['name']}")
        products.append(p)

    db.session.commit()
    return products


def seed_customers(admin):
    specs = [
        dict(
            first_name="Maria", last_name="Santos",
            gender="Female",
            contact_number="09171234567",
            home_address="123 Maharlika St., Brgy. San Isidro, Quezon City",
            primary_id_type="PhilHealth ID",
            is_id_verified=True,
        ),
        dict(
            first_name="Jose", last_name="Reyes",
            gender="Male",
            contact_number="09281234567",
            home_address="456 Rizal Ave., Brgy. Poblacion, Makati City",
            primary_id_type="Driver's License",
            is_id_verified=True,
        ),
        dict(
            first_name="Ana", last_name="Cruz",
            gender="Female",
            contact_number="09391234567",
            home_address="789 Mabini St., Brgy. Lipa, Batangas",
            primary_id_type="National ID",
            is_id_verified=True,
        ),
    ]

    customers = []
    for s in specs:
        existing = Customer.query.filter_by(
            first_name=s["first_name"], last_name=s["last_name"]
        ).first()
        if existing:
            print(f"[seed] Customer already exists: {s['first_name']} {s['last_name']}")
            customers.append(existing)
            continue
        c = Customer(**s, created_by_id=admin.id)
        db.session.add(c)
        db.session.flush()
        print(f"[seed] Created customer: {c.full_name}")
        customers.append(c)

    db.session.commit()
    return customers


def seed_transactions(products, customers, admin):
    # ── TX-1: Closed Sale — Hospital Bed sold to Santos ──────────────────────
    ref1 = f"SALE-{ref()}"
    tx1 = Transaction.query.filter_by(reference_no=ref1).first()
    if not tx1 and not Transaction.query.filter(
        Transaction.customer_id == customers[0].id,
        Transaction.transaction_type == "Sale"
    ).first():
        tx1 = Transaction(
            reference_no=ref1,
            customer_id=customers[0].id,
            customer_name=customers[0].full_name,
            processed_by=admin.id,
            transaction_type="Sale",
            fulfillment_type="Walk-in",
            delivery_status="N/A",
            tracking_status="COMPLETED",
            total_amount=Decimal("18500.00"),
            amount_paid=Decimal("18500.00"),
            balance_due=Decimal("0.00"),
            payment_method="Cash",
            payment_status="Fully Paid",
            status="Closed",
            deposit_amount=Decimal("0.00"),
            created_at=dt(today() - timedelta(days=15)),
        )
        db.session.add(tx1)
        db.session.flush()

        purchase1 = Purchase(
            transaction_id=tx1.id,
            product_id=products[0].id,
            customer_id=customers[0].id,
            product_name=products[0].name,
            product_type=products[0].equipment_type,
            product_asset_tag=products[0].asset_tag,
            product_condition=products[0].condition,
            product_category=products[0].category,
            product_cost_price=products[0].cost_price,
            product_sale_price=products[0].sale_price,
            quantity=1,
            unit_price=Decimal("18500.00"),
            total_price=Decimal("18500.00"),
        )
        db.session.add(purchase1)

        pay1 = Payment(
            transaction_id=tx1.id,
            payment_type="Sale Payment",
            amount=Decimal("18500.00"),
            payment_method="Cash",
            reference_number=f"CASH-{ref()}",
            status="Completed",
            verified_by_id=admin.id,
            verified_at=dt(today() - timedelta(days=15)),
        )
        db.session.add(pay1)

        # Inventory log — stock out
        log1 = InventoryLog(
            product_id=products[0].id,
            transaction_id=tx1.id,
            reference_no=ref1,
            reason_code="SALE",
            action="Stock Out — Sale",
            quantity=-1,
            balance_after=products[0].stock - 1,
            note=f"Sold 1 unit to {customers[0].full_name}",
            user_id=admin.id,
            user_name=admin.full_name,
        )
        db.session.add(log1)
        products[0].stock -= 1
        print(f"[seed] Created Sale transaction: {ref1}")
    else:
        print("[seed] Sale transaction already exists — skipping.")

    db.session.commit()

    # ── TX-2: Active Rental — Wheelchair rented to Reyes ────────────────────
    start2 = today() - timedelta(days=30)
    end2 = today() + timedelta(days=30)
    ref2 = f"RENT-{ref()}"
    if not Transaction.query.filter(
        Transaction.customer_id == customers[1].id,
        Transaction.transaction_type == "Rental"
    ).first():
        tx2 = Transaction(
            reference_no=ref2,
            customer_id=customers[1].id,
            customer_name=customers[1].full_name,
            processed_by=admin.id,
            transaction_type="Rental",
            fulfillment_type="Walk-in",
            delivery_status="N/A",
            tracking_status="ACTIVE",
            total_amount=Decimal("600.00"),
            amount_paid=Decimal("600.00"),
            balance_due=Decimal("0.00"),
            payment_method="Cash",
            payment_status="Fully Paid",
            status="Open",
            deposit_amount=Decimal("500.00"),
            created_at=dt(start2),
        )
        db.session.add(tx2)
        db.session.flush()

        rental2 = Rental(
            transaction_id=tx2.id,
            product_id=products[1].id,
            customer_id=customers[1].id,
            start_date=start2,
            expected_return_date=end2,
            monthly_rate=Decimal("600.00"),
            deposit_amount=Decimal("500.00"),
            deposit_status="Held",
            quantity=1,
            quantity_returned=0,
            status="Active",
        )
        db.session.add(rental2)
        db.session.flush()

        inv2 = RentalInvoice(
            rental_id=rental2.id,
            service_period_start=start2,
            service_period_end=start2 + relativedelta(months=1),
            amount_due=Decimal("600.00"),
            status="Paid",
        )
        db.session.add(inv2)
        db.session.flush()

        pay2 = Payment(
            transaction_id=tx2.id,
            invoice_id=inv2.id,
            payment_type="Rental Invoice",
            amount=Decimal("600.00"),
            payment_method="GCash",
            reference_number=f"GC-{ref()}",
            status="Completed",
            verified_by_id=admin.id,
            verified_at=dt(start2),
        )
        db.session.add(pay2)

        log2 = InventoryLog(
            product_id=products[1].id,
            transaction_id=tx2.id,
            reference_no=ref2,
            reason_code="RENTAL_OUT",
            action="Stock Out — Rental",
            quantity=-1,
            balance_after=products[1].stock - 1,
            note=f"Rented 1 unit to {customers[1].full_name}",
            user_id=admin.id,
            user_name=admin.full_name,
        )
        db.session.add(log2)
        products[1].stock -= 1
        print(f"[seed] Created active Rental transaction: {ref2}")
    else:
        print("[seed] Rental (Reyes) already exists — skipping.")

    db.session.commit()

    # ── TX-3: Returned Rental — Oxygen Concentrator returned by Cruz ─────────
    start3 = today() - timedelta(days=60)
    end3 = today() - timedelta(days=5)
    ref3 = f"RENT-{ref()}"
    if not Transaction.query.filter(
        Transaction.customer_id == customers[2].id,
        Transaction.transaction_type == "Rental"
    ).first():
        tx3 = Transaction(
            reference_no=ref3,
            customer_id=customers[2].id,
            customer_name=customers[2].full_name,
            processed_by=admin.id,
            transaction_type="Rental",
            fulfillment_type="Delivery",
            delivery_status="Delivered",
            tracking_status="COMPLETED",
            total_amount=Decimal("5000.00"),
            amount_paid=Decimal("5000.00"),
            balance_due=Decimal("0.00"),
            payment_method="Bank Transfer",
            payment_status="Fully Paid",
            status="Closed",
            deposit_amount=Decimal("1500.00"),
            distance_km=Decimal("7.50"),
            deposit_rule="Above 6 km",
            created_at=dt(start3),
        )
        db.session.add(tx3)
        db.session.flush()

        rental3 = Rental(
            transaction_id=tx3.id,
            product_id=products[2].id,
            customer_id=customers[2].id,
            start_date=start3,
            expected_return_date=end3,
            actual_return_date=end3,
            monthly_rate=Decimal("2500.00"),
            deposit_amount=Decimal("1500.00"),
            deposit_status="Refunded",
            quantity=1,
            quantity_returned=1,
            status="Returned",
            return_condition="Good",
            return_condition_notes="Equipment returned in good condition.",
        )
        db.session.add(rental3)
        db.session.flush()

        for month_offset in range(2):
            period_start = start3 + relativedelta(months=month_offset)
            period_end = period_start + relativedelta(months=1)
            inv = RentalInvoice(
                rental_id=rental3.id,
                service_period_start=period_start,
                service_period_end=period_end,
                amount_due=Decimal("2500.00"),
                status="Paid",
            )
            db.session.add(inv)
            db.session.flush()
            pay = Payment(
                transaction_id=tx3.id,
                invoice_id=inv.id,
                payment_type="Rental Invoice",
                amount=Decimal("2500.00"),
                payment_method="Bank Transfer",
                reference_number=f"BT-{ref()}",
                status="Completed",
                verified_by_id=admin.id,
                verified_at=dt(period_start + timedelta(days=2)),
            )
            db.session.add(pay)

        log3 = InventoryLog(
            product_id=products[2].id,
            transaction_id=tx3.id,
            reference_no=ref3,
            reason_code="RENTAL_RETURN",
            action="Stock In — Return",
            quantity=1,
            balance_after=products[2].stock,
            note=f"Returned by {customers[2].full_name} — Good condition",
            user_id=admin.id,
            user_name=admin.full_name,
        )
        db.session.add(log3)
        print(f"[seed] Created returned Rental transaction: {ref3}")
    else:
        print("[seed] Rental (Cruz) already exists — skipping.")

    db.session.commit()


def seed_expenses(products, admin):
    if Expense.query.count() >= 3:
        print("[seed] Expenses already present — skipping.")
        return

    expenses = [
        Expense(
            category="Supplier Refill",
            expense_title="Prime Gas oxygen refill batch",
            amount=Decimal("4500.00"),
            refill_quantity=5,
            description="Monthly oxygen tank refill from Prime Gas — 5 units.",
            product_id=products[2].id,
            recorded_by_id=admin.id,
            date_incurred=today() - timedelta(days=10),
        ),
        Expense(
            category="Maintenance",
            expense_title="Hospital bed frame repair",
            amount=Decimal("800.00"),
            description="Welding repair on side rail of HB-001.",
            product_id=products[0].id,
            recorded_by_id=admin.id,
            date_incurred=today() - timedelta(days=20),
        ),
        Expense(
            category="Utilities",
            expense_title="Electricity bill — October",
            amount=Decimal("3200.00"),
            description="Monthly electricity expense for the store and warehouse.",
            recorded_by_id=admin.id,
            date_incurred=today() - timedelta(days=5),
        ),
    ]

    for e in expenses:
        db.session.add(e)
    db.session.commit()
    print(f"[seed] Created {len(expenses)} expenses.")


def seed_stock_adjustments(products, admin):
    staff = User.query.filter_by(role="Staff").first()
    if StockAdjustment.query.count() >= 3:
        print("[seed] Stock adjustments already present — skipping.")
        return

    adjs = [
        StockAdjustment(
            product_id=products[0].id,
            counted_qty=products[0].stock,
            system_qty=products[0].stock,
            variance=0,
            reason_code="Physical Count",
            note="Monthly physical count — counts match system.",
            status="Approved",
            requested_by_id=staff.id if staff else admin.id,
            requested_at=dt(today() - timedelta(days=3)),
            reviewed_by_id=admin.id,
            reviewed_at=dt(today() - timedelta(days=3)),
        ),
        StockAdjustment(
            product_id=products[1].id,
            counted_qty=products[1].stock + 1,
            system_qty=products[1].stock,
            variance=1,
            reason_code="Physical Count",
            note="Found 1 extra wheelchair unit in back storage.",
            status="Pending",
            requested_by_id=staff.id if staff else admin.id,
            requested_at=dt(today() - timedelta(days=1)),
        ),
        StockAdjustment(
            product_id=products[2].id,
            counted_qty=products[2].stock - 1,
            system_qty=products[2].stock,
            variance=-1,
            reason_code="Damaged",
            note="One concentrator unit found non-functional after inspection.",
            status="Pending",
            requested_by_id=staff.id if staff else admin.id,
            requested_at=dt(today()),
        ),
    ]

    for a in adjs:
        db.session.add(a)
    db.session.commit()
    print(f"[seed] Created {len(adjs)} stock adjustments.")


def seed_inventory_restock_log(products, admin):
    """Add a restock log entry so Movement Log isn't empty."""
    if InventoryLog.query.filter_by(reason_code="RESTOCK").first():
        print("[seed] Restock log already present — skipping.")
        return

    log = InventoryLog(
        product_id=products[0].id,
        reason_code="RESTOCK",
        action="Stock In — Restock",
        quantity=10,
        balance_after=products[0].stock + 10,
        note="Initial stock replenishment from supplier.",
        user_id=admin.id,
        user_name=admin.full_name,
        created_at=dt(today() - timedelta(days=30)),
    )
    db.session.add(log)
    db.session.commit()
    print("[seed] Created restock inventory log.")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    with app.app_context():
        admin = User.query.filter_by(role="Administrator").first()
        if not admin:
            print("[seed] ERROR: No Administrator user found. Run seed_users.py first.")
            return

        print("\n=== CareMed Demo Seed ===\n")
        seed_settings()
        products = seed_products()
        customers = seed_customers(admin)
        seed_transactions(products, customers, admin)
        seed_expenses(products, admin)
        seed_stock_adjustments(products, admin)
        seed_inventory_restock_log(products, admin)
        print("\n=== Seed complete. ===\n")


if __name__ == "__main__":
    main()
