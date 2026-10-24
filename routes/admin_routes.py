from flask import Blueprint, render_template, url_for, redirect, flash, request, jsonify, current_app, send_from_directory, abort
from flask_login import current_user
from extensions import db, limiter, csrf
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, and_
from flask_login import login_required
from functools import wraps
from models.product import Product, InventoryLog, Transaction, Purchase, Payment, Rental, RentalInvoice, Expense, PaymentProof, TankStatus, RentalTank, RentalTankLog, CustomerDeposit
from models.customer import Customer
from models.users import User, SecurityLog, BlockedIP, Permission
from models.settings import (
    SystemSetting,
    format_deposit_tiers,
    parse_deposit_tiers,
    resolve_delivery_deposit,
)
from models.operations import StockAdjustment, VoidRequest
from flask_mail import Message
from flask import current_app
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import joinedload, selectinload
import os   
import uuid
import random, string
from utils.backup import create_backup, get_all_backups
from utils.report_exports import (
    build_inventory_export,
    build_movements_export,
    build_rentals_export,
    build_sales_export,
    build_supplier_export,
    build_tank_export,
    parse_range,
    xlsx_response,
)
from flask import send_file, Response, stream_with_context
import json
import time
from sqlalchemy import case, func


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Chapter III stakeholder roles → default permission bundles. Administrators
# always bypass permission checks; these presets make Staff accounts match the
# duties described in the thesis, while the edit modal still allows overrides.
DAMAGE_CONDITIONS = ('Minor Damage', 'Major Damage', 'Total Loss')
DAMAGE_REASON_CODES = (
    'Cracked',
    'Broken',
    'Leak',
    'Missing Parts',
    'Electrical Fault',
    'Lost',
    'Other',
)

ROLE_PRESETS = {
    'Owner/Admin': {
        'role': 'Administrator',
        'can_manage_customers': True,
        'can_verify_customers': True,
        'can_manage_products': True,
        'can_update_stock': True,
        'can_process_transactions': True,
        'can_confirm_payments': True,
        'can_export_transactions': True,
        'can_manage_expenses': True,
        'can_view_reports': True,
        'can_view_logs': True,
        'can_view_active_rentals': True,
    },
    'Counter Staff': {
        'role': 'Staff',
        'can_manage_customers': True,
        'can_verify_customers': True,
        'can_process_transactions': True,
        'can_confirm_payments': True,
        'can_view_active_rentals': True,
    },
    'Inventory Custodian': {
        'role': 'Staff',
        'can_manage_products': True,
        'can_update_stock': True,
        'can_process_transactions': True,
        'can_view_logs': True,
        'can_view_reports': True,
        'can_view_active_rentals': True,
    },
    'Delivery Personnel': {
        'role': 'Staff',
        'can_view_active_rentals': True,
    },
}

def admin_or_staff_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        authorized_roles = ['Administrator', 'Staff']

        if not current_user.is_authenticated or current_user.role.strip() not in authorized_roles:
            try:
                log = SecurityLog(
                    ip_address=request.remote_addr,
                    event_type="Unauthorized Access",
                    description=f"User with role '{getattr(current_user, 'role', 'None')}' tried to access: {request.path}",
                    user_id=current_user.id if current_user.is_authenticated else None,
                    user_email=current_user.email if current_user.is_authenticated else None,
                    user_agent=request.headers.get('User-Agent', 'Unknown')[:255],
                    severity='High',
                    is_suspicious=True
                )
                db.session.add(log)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Failed to log unauthorized access: {e}")
                
            flash("Unauthorized access.", "error")
            return redirect(url_for('user.homepage'))
            
        return f(*args, **kwargs)
    return decorated_function

def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            
            if getattr(current_user, 'role', '') == 'Administrator':
                return f(*args, **kwargs)
            
            user_perms = Permission.query.filter_by(user_id=current_user.id).first()
            

            if user_perms and getattr(user_perms, permission_name, False):
                return f(*args, **kwargs)

            flash("You do not have permission to access this feature.", "danger")
            return redirect(request.referrer or url_for('admin.dashboard'))
            
        return decorated_function
    return decorator

from sqlalchemy import func

def get_cogs_category(product):
    """Smart category assignment for auto-generated Cost of Sales expenses."""
    if product.is_refillable:
        return 'Oxygen Refill Cost'
    et = (product.equipment_type or '').lower()
    name = (product.name or '').lower()
    if 'medical supplies' in et or 'medical supplies' in name:
        return 'Medical Supplies Purchase'
    if 'supplies' in et or 'supplies' in name:
        return 'Medical Supplies Purchase'
    return 'Equipment Purchase'

COST_OF_SALES_CATEGORIES = {
    'Oxygen Refill Cost',
    'Equipment Purchase',
    'Medical Supplies Purchase',
    'Inventory Purchase',
}
 
OPERATING_EXPENSE_CATEGORIES = {
    'Utilities',
    'Rent',
    'Salaries',
    'Maintenance',
    'Government Fees',
    'Insurance',
    'Transportation',
    'Office Supplies',
    'Other',
}

ALL_EXPENSE_CATEGORIES_ORDERED = [
    # Cost of Sales
    'Oxygen Refill Cost',
    'Equipment Purchase',
    'Medical Supplies Purchase',
    'Inventory Purchase',
    # Operating Expenses
    'Utilities',
    'Rent',
    'Salaries',
    'Maintenance',
    'Government Fees',
    'Insurance',
    'Transportation',
    'Office Supplies',
    'Other',
]

@admin_bp.route("/dashboard")
@login_required
@admin_or_staff_required
def dashboard():
    return render_template("admin/dashboard.html")

def get_date_boundaries(period, custom_start=None, custom_end=None):
    now = datetime.now()

    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end

    elif period == 'this_week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return start, end

    elif period == 'this_month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(month=start.month % 12 + 1, year=start.year + (start.month // 12)) 
               if start.month < 12 else datetime(start.year + 1, 1, 1))
        return start, end

    elif period == 'last_month':
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_this_month
        start = (first_of_this_month.replace(year=first_of_this_month.year - 1, month=12) 
                 if first_of_this_month.month == 1 
                 else first_of_this_month.replace(month=first_of_this_month.month - 1))
        return start, end

    elif period == 'this_year':
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = datetime(now.year + 1, 1, 1)
        return start, end

    elif period == 'custom' and custom_start and custom_end:
        try:
            start = datetime.strptime(custom_start, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
            end = datetime.strptime(custom_end, '%Y-%m-%d').replace(hour=0, minute=0, second=0) + timedelta(days=1)
            return start, end
        except ValueError:
            pass  # Fallback if parsing fails

    elif period == 'all_time':
        return None, None

    # Default fallback
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None


@admin_bp.route("/dashboard/data")
@login_required
@admin_or_staff_required
def dashboard_data():
    try:
        period = request.args.get('period', 'this_month')
        custom_start = request.args.get('start_date')
        custom_end = request.args.get('end_date')

        start_date, end_date = get_date_boundaries(period, custom_start, custom_end)

        def apply_date_filter(query, date_column=Transaction.created_at):
            if start_date:
                query = query.filter(date_column >= start_date)
            if end_date:
                query = query.filter(date_column < end_date)
            return query

        sales_rentals_query = db.session.query(
            func.coalesce(
                func.sum(case((Transaction.transaction_type == "Sale", Transaction.amount_paid), else_=0)),
                Decimal("0.00")
            ),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.transaction_type == "Rental", 
                         Transaction.amount_paid - func.coalesce(
                             db.select(func.sum(Payment.amount))
                             .where(
                                 Payment.transaction_id == Transaction.id, 
                                 Payment.payment_type == "InitialFill", 
                                 Payment.status == "Completed"
                             )
                             .scalar_subquery(), 
                             0
                         )), 
                        else_=0)
                ),
                Decimal("0.00")
            )
        ).filter(Transaction.transaction_type.in_(["Sale", "Rental"]))
        
        sales_rentals_query = apply_date_filter(sales_rentals_query)
        sales_and_rentals = sales_rentals_query.first()
        
        total_sales = float(sales_and_rentals[0]) if sales_and_rentals and sales_and_rentals[0] is not None else 0.0
        total_rentals = float(sales_and_rentals[1]) if sales_and_rentals and sales_and_rentals[1] is not None else 0.0

        cogs_query = db.session.query(
            func.coalesce(
                func.sum(
                    func.coalesce(Purchase.product_cost_price, 0)
                    * func.coalesce(Purchase.quantity, 0)
                ), 
                0
            )
        ).join(Transaction).filter(Transaction.transaction_type == "Sale")
        
        cogs_query = apply_date_filter(cogs_query)
        total_cogs = cogs_query.scalar()
        
        sales_net = total_sales - float(total_cogs or 0.0)

        initial_fill_payments_query = db.session.query(
            func.coalesce(func.sum(Payment.amount), 0)
        ).join(Transaction, Payment.transaction_id == Transaction.id).filter(
            Payment.payment_type == "InitialFill", 
            Payment.status == "Completed"
        )
        initial_fill_payments_query = apply_date_filter(initial_fill_payments_query)
        initial_fill_payments_total = initial_fill_payments_query.scalar() or 0.0

        initial_fill_tanks_query = db.session.query(
            func.coalesce(func.sum(Rental.quantity), 0)
        ).join(Transaction, Rental.transaction_id == Transaction.id).join(
            Payment, Payment.transaction_id == Transaction.id
        ).filter(
            Payment.payment_type == "InitialFill", 
            Payment.status == "Completed"
        )
        initial_fill_tanks_query = apply_date_filter(initial_fill_tanks_query)
        initial_fill_tanks_count = initial_fill_tanks_query.scalar() or 0

        if int(initial_fill_tanks_count) == 0:
            fallback_tanks_query = db.session.query(
                func.coalesce(func.sum(Transaction.quantity), 0)
            ).join(Payment, Payment.transaction_id == Transaction.id).filter(
                Payment.payment_type == "InitialFill", 
                Payment.status == "Completed"
            )
            fallback_tanks_query = apply_date_filter(fallback_tanks_query)
            initial_fill_tanks_count = fallback_tanks_query.scalar() or 0

        refill_stats_query = db.session.query(
            func.coalesce(func.sum(case((Transaction.transaction_type == "Refill", Transaction.total_amount), else_=0)), 0),
            func.coalesce(func.sum(case((
                Transaction.transaction_type == "Refill",
                func.coalesce(Transaction.total_amount, 0)
                - func.coalesce(Transaction.quantity, 0) * func.coalesce(Transaction.refill_cost_per_unit, 0),
            ), else_=0)), 0),
            func.coalesce(func.sum(case((Transaction.transaction_type == "Refill", Transaction.quantity), else_=0)), 0),
        )
        refill_stats_query = apply_date_filter(refill_stats_query)
        refill_stats = refill_stats_query.first()
        
        base_refill_income = float(refill_stats[0]) if refill_stats and refill_stats[0] is not None else 0.0
        base_refill_profit = float(refill_stats[1]) if refill_stats and refill_stats[1] is not None else 0.0
        base_refills_count = int(refill_stats[2]) if refill_stats and refill_stats[2] is not None else 0

        total_refills_count = base_refills_count + int(initial_fill_tanks_count)
        total_refill_income = base_refill_income + float(initial_fill_payments_total)
        total_refill_profit = base_refill_profit + float(initial_fill_payments_total)

        active_rentals_count = Rental.query.filter_by(status="Active").count() or 0

        # Calculate active customer deposits (status == 'Held')
        customer_deposits_total = db.session.query(
            func.coalesce(func.sum(CustomerDeposit.amount), Decimal("0.00"))
        ).filter(CustomerDeposit.status == "Held").scalar() or 0.00

        # Calculate total freight expenses filtered by date period
        freight_expenses_query = db.session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        ).filter(Expense.category == 'Freight')
        
        if hasattr(Expense, 'created_at'):
            freight_expenses_query = apply_date_filter(freight_expenses_query, Expense.created_at)
        elif hasattr(Expense, 'date'):
            freight_expenses_query = apply_date_filter(freight_expenses_query, Expense.date)
        
        total_freight = float(freight_expenses_query.scalar() or 0.0)

        expenses_query = db.session.query(
            func.coalesce(func.sum(Expense.amount), 0)
        )
        if hasattr(Expense, 'created_at'):
            expenses_query = apply_date_filter(expenses_query, Expense.created_at)
        elif hasattr(Expense, 'date'):
            expenses_query = apply_date_filter(expenses_query, Expense.date)
        total_expenses = expenses_query.scalar() or 0.0

        product_stats = (
            db.session.query(
                func.coalesce(func.sum(Product.stock), 0),
                func.coalesce(func.sum(case((Product.stock <= Product.reorder_level, 1), else_=0)), 0)
            )
            .filter(Product.is_active == True, Product.is_refillable == False)
            .first()
        )
        product_inventory = int(product_stats[0]) if product_stats and product_stats[0] is not None else 0
        low_stock_count = int(product_stats[1]) if product_stats and product_stats[1] is not None else 0

        raw_tank_data = (
            TankStatus.query.join(Product)
            .filter(
                Product.is_active == True,
                db.or_(
                    Product.equipment_type == "Oxygen Tank",
                    Product.category == "Oxygen Tank"
                )
            )
            .all()
        )

        tank_aggregation = {}
        total_tank_count = 0

        for tank in raw_tank_data:
            key = (tank.product.name, tank.product.size)
            if key not in tank_aggregation:
                tank_aggregation[key] = {
                    "name": tank.product.name,
                    "size": tank.product.size,
                    "product_id": tank.product.id,
                    "total_owned": 0,
                    "rented_out": 0,
                    "full_in_stock": 0,
                    "empty_in_stock": 0,
                }

            tank_aggregation[key]["total_owned"] += tank.total_owned or 0
            tank_aggregation[key]["rented_out"] += tank.rented_out or 0
            tank_aggregation[key]["full_in_stock"] += tank.full_in_stock or 0
            tank_aggregation[key]["empty_in_stock"] += tank.empty_in_stock or 0

            total_tank_count += ((tank.full_in_stock or 0) + (tank.empty_in_stock or 0) + (tank.rented_out or 0))

        combined_tank_statuses = list(tank_aggregation.values())
        total_inventory = product_inventory + total_tank_count

        all_products = Product.query.filter(
            Product.is_refillable == False,
            Product.is_active == True,
            Product.condition.in_(["Brand New", "Used"]),
        ).all()

        active_rented_units = (
            db.session.query(
                Rental.product_id,
                func.sum(Rental.quantity - Rental.quantity_returned),
            )
            .filter(Rental.status == "Active")
            .group_by(Rental.product_id)
            .all()
        )

        rented_map = {prod_id: count for prod_id, count in active_rented_units if count is not None}

        assets_aggregation = {}
        for prod in all_products:
            prod_name = prod.name
            if prod_name not in assets_aggregation:
                assets_aggregation[prod_name] = {
                    "name": prod_name,
                    "total_stock": 0,
                    "rented_count": 0,
                    "used_count": 0,
                    "brand_new_count": 0,
                }

            assets_aggregation[prod_name]["total_stock"] += prod.stock or 0
            assets_aggregation[prod_name]["rented_count"] += rented_map.get(prod.id, 0)

            condition_str = (prod.condition or "").strip()
            if condition_str == "Brand New":
                assets_aggregation[prod_name]["brand_new_count"] += prod.stock or 0
            elif condition_str == "Used":
                assets_aggregation[prod_name]["used_count"] += prod.stock or 0

        standard_assets = list(assets_aggregation.values())

        return jsonify({
            "total_sales": float(total_sales),
            "sales_net": float(sales_net),
            "total_rentals": float(total_rentals),
            "total_refill_income": float(total_refill_income),
            "total_refill_profit": float(total_refill_profit),
            "total_refills_count": int(total_refills_count),
            "active_rentals_count": int(active_rentals_count),
            "total_inventory": int(total_inventory),
            "customer_deposits": float(customer_deposits_total),
            "total_freight": float(total_freight),
            "low_stock_count": int(low_stock_count),
            "total_expenses": float(total_expenses),
            "tank_statuses": combined_tank_statuses,
            "standard_assets": standard_assets,
        })
        
    except Exception:
        current_app.logger.exception("Critical error encountered while fetching admin dashboard metrics.")
        return jsonify({
            "error": "An internal error occurred while processing dashboard analytics. Please try again later."
        }), 500
          
@admin_bp.route('/process-refill-transaction', methods=['POST'])
@login_required
@admin_or_staff_required
def process_refill_transaction():
    buyer_type = request.form.get('refill_buyer_type')
    tank_size = request.form.get('tank_size') or request.form.get('tank_size_select') or request.form.get('tank_size_text')
    quantity = request.form.get('quantity', type=int)
    
    serial_list = request.form.getlist('serial_numbers')
    swapped_serials = request.form.getlist('swapped_rental_serial')

    try:
        raw_form_amount = request.form.get('amount')
        if isinstance(raw_form_amount, list):
            raw_form_amount = raw_form_amount[0]
        form_amount = Decimal(str(raw_form_amount or '0').replace(',', '') or '0')
    except (ValueError, TypeError, InvalidOperation):
        flash("Invalid numeric input for amount.", "danger")
        return redirect(request.referrer or url_for('admin.dashboard'))

    try:
        raw_voucher = request.form.get('voucher_amount', '0')
        if isinstance(raw_voucher, list):
            raw_voucher = raw_voucher[0]
        voucher_amount = Decimal(str(raw_voucher).replace(',', '') or '0')
    except (ValueError, TypeError, InvalidOperation):
        flash("Invalid numeric input for voucher amount.", "danger")
        return redirect(request.referrer or url_for('admin.dashboard'))

    try:
        raw_delivery = request.form.get('delivery_fee', '0')
        if isinstance(raw_delivery, list):
            raw_delivery = raw_delivery[0]
        delivery_fee = Decimal(str(raw_delivery).replace(',', '') or '0')
    except (ValueError, TypeError, InvalidOperation):
        flash("Invalid numeric input for delivery fee.", "danger")
        return redirect(request.referrer or url_for('admin.dashboard'))

    try:
        raw_amount_paid = request.form.get('amount_paid')
        if isinstance(raw_amount_paid, list):
            raw_amount_paid = raw_amount_paid[0]
        amount_paid = Decimal(str(raw_amount_paid or form_amount).replace(',', '') or '0')
    except (ValueError, TypeError, InvalidOperation):
        amount_paid = form_amount

    if not form_amount or not quantity or quantity <= 0:
        flash("Transaction failed: Please ensure all fields are filled correctly.", "danger")
        return redirect(request.referrer or url_for('admin.dashboard'))

    if buyer_type == 'registered' and len(serial_list) != quantity:
        flash(f"Data Mismatch: You specified {quantity} tank(s), but only entered {len(serial_list)} incoming serial number(s).", "danger")
        return redirect(request.referrer or url_for('admin.dashboard'))

    refill_unit_cost = form_amount / Decimal(str(quantity))
    net_total = max((form_amount + delivery_fee) - voucher_amount, Decimal("0.00"))

    try:
        customer_id = None
        display_name = "Walk-in Customer"
        product = None
        serial_display_parts = []
        
        if buyer_type == 'registered':
            customer_id = request.form.get('refill_customer_id')
            if isinstance(customer_id, list):
                customer_id = customer_id[0]
                
            customer = db.session.get(Customer, int(customer_id)) if customer_id else None
            if not customer:
                flash("System Error: Could not verify the registered customer.", "danger")
                return redirect(request.referrer or url_for('admin.dashboard'))
            display_name = customer.full_name

            if swapped_serials and serial_list:
                for target_serial, new_serial in zip(swapped_serials, serial_list):
                    rental_tank = RentalTank.query.join(Rental).filter(
                        Rental.customer_id == customer_id,
                        RentalTank.serial_number == target_serial.strip(),
                        RentalTank.status == "Active"
                    ).first()
                    
                    if rental_tank:
                        if not product:
                            product = rental_tank.rental.product
                        
                        old_serial = rental_tank.serial_number
                        new_serial_clean = new_serial.strip()

                        if old_serial != new_serial_clean:
                            tank_log = RentalTankLog(
                                rental_id=rental_tank.rental_id,
                                tank_id=rental_tank.id,
                                old_serial_number=old_serial,
                                new_serial_number=new_serial_clean,
                                reason="Tank Refill / Asset Exchange",
                                changed_by_id=current_user.id
                            )
                            db.session.add(tank_log)

                            rental_tank.serial_number = new_serial_clean
                            db.session.add(rental_tank)
                            
                            serial_display_parts.append(f"{old_serial} → {new_serial_clean}")
                        else:
                            serial_display_parts.append(new_serial_clean)

            if not product:
                selected_tank_val = tank_size or ''
                product_name = selected_tank_val.split(' - ')[0] if ' - ' in selected_tank_val else selected_tank_val
                product = Product.query.filter_by(name=product_name.strip(), is_refillable=True).first()

            if product:
                tank_status = TankStatus.query.filter_by(product_id=product.id).first()
                if not tank_status:
                    tank_status = TankStatus(product_id=product.id, full_in_stock=0, empty_in_stock=0)
                    db.session.add(tank_status)

                if tank_status.full_in_stock < quantity:
                    flash(f"Inventory Alert: Insufficient full tanks in stock for {product.name}. Available full: {tank_status.full_in_stock}", "danger")
                    return redirect(request.referrer or url_for('admin.dashboard'))
                
                tank_status.full_in_stock -= quantity
                tank_status.empty_in_stock += quantity
            else:
                flash("Inventory Error: Could not match refillable product inventory item.", "danger")
                return redirect(request.referrer or url_for('admin.dashboard'))

        else:
            unreg_name_raw = request.form.get('unregistered_customer_name', '')
            if isinstance(unreg_name_raw, list):
                unreg_name_raw = unreg_name_raw[0]
            display_name = unreg_name_raw.strip() or "Walk-in Customer"
            
            unreg_products = request.form.getlist('unregistered_product_size')
            
            selected_tank_val = (unreg_products[0] if unreg_products else None) or tank_size or ''
            product_name = selected_tank_val.split(' - ')[0] if ' - ' in selected_tank_val else selected_tank_val
            
            product = Product.query.filter_by(name=product_name.strip(), is_refillable=True).first()
            
            if serial_list:
                serial_display_parts = [s.strip() for s in serial_list if s.strip()]

            if product:
                tank_status = TankStatus.query.filter_by(product_id=product.id).first()
                if not tank_status:
                    tank_status = TankStatus(product_id=product.id, full_in_stock=0, empty_in_stock=0)
                    db.session.add(tank_status)

                if tank_status.full_in_stock < quantity:
                    flash(f"Inventory Alert: Insufficient full tanks in stock for {product.name}. Available full: {tank_status.full_in_stock}", "danger")
                    return redirect(request.referrer or url_for('admin.dashboard'))
                
                tank_status.full_in_stock -= quantity
                tank_status.empty_in_stock += quantity
            else:
                flash("Inventory Error: Could not match refillable product inventory item for walk-in.", "danger")
                return redirect(request.referrer or url_for('admin.dashboard'))

        final_serials_str = ", ".join(serial_display_parts) if serial_display_parts else "N/A"
        
        fulfillment_raw = request.form.get("fulfillment_type", "Walk-In")
        if isinstance(fulfillment_raw, list):
            fulfillment_raw = fulfillment_raw[0]
        fulfillment_type = fulfillment_raw

        new_transaction = Transaction(
            reference_no="TEMP",  
            transaction_type="Refill",
            product_id=product.id if product else None,
            customer_id=customer_id,
            customer_name=display_name,
            walk_in_tank_size=tank_size if buyer_type != 'registered' else None,
            quantity=quantity,
            delivery_fee=delivery_fee,
            voucher_amount=voucher_amount,
            total_amount=net_total,
            refill_cost_per_unit=refill_unit_cost,
            serial_numbers=final_serials_str,
            status="Closed",
            fulfillment_type=fulfillment_type,
            processed_by=current_user.id
        )
        db.session.add(new_transaction)
        db.session.flush() 

        new_transaction.update_totals()
        new_transaction.reference_no = f"RFL-{new_transaction.id:06d}"

        if amount_paid > 0:
            pm_raw = request.form.get("payment_method", "Cash")
            if isinstance(pm_raw, list):
                pm_raw = pm_raw[0]
            payment_method = (pm_raw or "Cash").strip()
            
            ref_num_raw = request.form.get("reference_number", "")
            if isinstance(ref_num_raw, list):
                ref_num_raw = ref_num_raw[0]
            reference_number = (ref_num_raw or "").strip()

            if payment_method.lower() == "cash":
                reference_number = None
            else:
                if not reference_number:
                    db.session.rollback()
                    flash("Reference number is required for non-cash payments.", "danger")
                    return redirect(request.referrer or url_for('admin.dashboard'))

                existing_payment = Payment.query.filter_by(
                    reference_number=reference_number
                ).first()

                if existing_payment:
                    db.session.rollback()
                    flash("Payment reference number already exists.", "danger")
                    return redirect(request.referrer or url_for('admin.dashboard'))

            new_transaction.payment_method = payment_method

            db.session.add(Payment(
                transaction_id=new_transaction.id,
                invoice_id=None,
                payment_type="Refill",
                amount=amount_paid,
                payment_method=payment_method,
                reference_number=reference_number,
                status="Completed",
                verified_by_id=current_user.id,
                verified_at=datetime.utcnow()
            ))

        log = InventoryLog(
            product_id=product.id if product else None,
            action="Refill Service Completed & Swapped" if buyer_type == 'registered' else "Walk-in Refill Service Completed",
            quantity=quantity,
            note=f"Processed refill for {display_name}. Subtotal: {form_amount} PHP, Net Total: {net_total} PHP.",
            user_id=current_user.id,
            user_name=getattr(current_user, 'full_name', 'System Administrator')
        )
        db.session.add(log)
        
        db.session.commit()
        flash(f"Refill transaction successfully processed for {display_name}.", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"REFILL_ERROR: {str(e)}")
        flash(f"An unexpected error occurred while saving the transaction: {str(e)}", "danger")

    return redirect(url_for("admin.transactions"))

@admin_bp.route('/customers')
@login_required
@admin_or_staff_required
@permission_required('can_manage_customers')
def customers():
    page         = request.args.get('page', 1, type=int)
    limit        = request.args.get('limit', 10, type=int)
    search_query = request.args.get('q', '').strip()
    filter_type  = request.args.get('filter', '')         
 
    query = Customer.query
 
    if search_query:
        query = query.filter(or_(
            Customer.first_name.ilike(f"%{search_query}%"),
            Customer.last_name.ilike(f"%{search_query}%"),
            Customer.contact_number.ilike(f"%{search_query}%")
        ))
 
    if filter_type == 'overdue_invoices':
        from models.product import RentalInvoice, Rental as RentalModel
        today = date.today()
        overdue_customer_ids = db.session.query(
            RentalModel.customer_id
        ).join(
            RentalInvoice, RentalInvoice.rental_id == RentalModel.id
        ).filter(
            RentalInvoice.status != 'Paid',
            RentalInvoice.service_period_start < today
        ).distinct().subquery()
 
        query = query.filter(Customer.id.in_(overdue_customer_ids))
 
    elif filter_type == 'pending_id':

        query = query.filter(
            Customer.is_id_verified == False,
            Customer.valid_id_path != None
        )
 
    elif filter_type == 'inactive_open':
        open_txn_customer_ids = db.session.query(
            Transaction.customer_id
        ).filter(
            Transaction.status == 'Open'
        ).distinct().subquery()
 
        query = query.filter(
            Customer.is_active == False,
            Customer.id.in_(open_txn_customer_ids)
        )
    
 
    pagination = query.order_by(Customer.last_name.asc()).paginate(
        page=page,
        per_page=limit,
        error_out=False
    )
 
    return render_template(
        "admin/customers.html",
        customers=pagination.items,
        pagination=pagination,
        search_query=search_query,
        current_limit=limit,
        current_filter=filter_type      
    )

@admin_bp.route('/get_customer/<int:id>')
@login_required
@admin_or_staff_required
def get_customer(id):
    try:
        customer = Customer.query.options(
            db.joinedload(Customer.user)
        ).get(id)

        if not customer:
            return jsonify({
                "status": "error",
                "message": "Customer record not found."
            }), 404

        profile_url = None
        if customer.user and customer.user.profile_path:
            if customer.user.profile_path.startswith(('http://', 'https://')):
                profile_url = customer.user.profile_path
            else:
                profile_url = url_for('static', filename=customer.user.profile_path)

        return jsonify({
            "status": "success",
            "data": {
                "id": customer.id,
                "first_name": customer.first_name or "",
                "last_name": customer.last_name or "",
                "full_name": customer.full_name or "", 
                
                "contact_number": customer.contact_number or "",
                "secondary_contact_number": customer.secondary_contact_number or "",
                "home_address": customer.home_address or "",
                
                "gender": customer.gender or "",
                
                "is_active": customer.is_active,
                "is_id_verified": customer.is_id_verified,
                
                "primary_id_type": customer.primary_id_type or "",
                "secondary_id_type": customer.secondary_id_type or "",
                
                "valid_id_path": url_for('static', filename=customer.valid_id_path) if customer.valid_id_path else None,
                "secondary_id_path": url_for('static', filename=customer.secondary_id_path) if customer.secondary_id_path else None,
                "proof_of_billing_path": url_for('static', filename=customer.proof_of_billing_path) if customer.proof_of_billing_path else None,
                
                "id_uploaded_at": customer.id_uploaded_at.strftime('%b %d, %Y %I:%M %p') if customer.id_uploaded_at else "Never",
                
                "has_online_account": True if customer.user_id else False,
                "email": customer.user.email if customer.user else "Walk-in / No Email",
                "profile_path": profile_url,
                
                "created_at": customer.created_at.strftime('%Y-%m-%d %H:%M:%S') if customer.created_at else None
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching customer {id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "An internal server error occurred while retrieving customer data."
        }), 500
        
        
@admin_bp.route('/customers/<int:id>')
@login_required
@admin_or_staff_required
def customer_details(id):
    customer = Customer.query.get_or_404(id)

    regular_txns = Transaction.query.filter_by(customer_id=id).all()
    refill_txns = Transaction.query.filter_by(customer_id=id, transaction_type="Refill").all()

    for tx in regular_txns:
        if not hasattr(tx, 'transaction_type'):
            tx.transaction_type = "Standard"

    combined_list = list(regular_txns) + list(refill_txns)

    transactions = sorted(
        combined_list,
        key=lambda x: x.created_at if getattr(x, 'created_at', None) else datetime.min,
        reverse=True
    )

    return render_template('admin/customer_details.html', customer=customer, transactions=transactions)

@admin_bp.route('/customers/<int:id>/verify', methods=['POST'])
@login_required
@admin_or_staff_required
def verify_customer(id):
    customer = Customer.query.get_or_404(id)
    
    if customer.is_id_verified:
        flash(f"Notice: {customer.full_name} is already a verified user.", "info")
        return redirect(url_for('admin.customer_details', id=id))

    try:
        customer.is_id_verified = True
        db.session.commit()
        flash(f"Identity Verification Complete: {customer.full_name} has been successfully verified.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Verification Failed for ID {id}: {str(e)}") 
        flash("An internal error occurred while processing the verification. Please refresh and try again.", "danger")
        
    return redirect(url_for('admin.customer_details', id=id))

@admin_bp.route('/customers/<int:id>/unverify', methods=['POST'])
@login_required
@admin_or_staff_required
def unverify_customer(id):
    customer = Customer.query.get_or_404(id)
    
    try:
        customer.is_id_verified = False
        db.session.commit()
        flash(f"Verification Revoked: {customer.full_name}'s identity status has been reset to unverified.", "warning")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Revoke Error for ID {id}: {str(e)}")
        flash("Action Failed: System encountered an error while revoking verification. Please try again.", "danger")
        
    return redirect(url_for('admin.customer_details', id=id))


@admin_bp.route('/admin/add-customer', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_customers')
def add_customer():

    if current_user.role not in ['Administrator', 'Staff']:
        flash("Unauthorized access.", "error")
        return redirect(url_for('user.homepage'))

    first_name = request.form.get('first_name', '').strip().title()
    last_name = request.form.get('last_name', '').strip().title()
    contact_number = request.form.get('contact_number', '').strip()
    
    secondary_contact = request.form.get('secondary_contact_number', '')
    secondary_contact_number = secondary_contact.strip() if secondary_contact else None
    
    home_address = request.form.get('home_address', '').strip()
    gender = request.form.get('gender')
    primary_id_type = request.form.get('primary_id_type')
    secondary_id_type = request.form.get('secondary_id_type')

    if not all([first_name, last_name, contact_number]):
        flash("Basic details (Name and Primary Contact) are required.", "error")
        return redirect(request.referrer or url_for('admin.customers'))

    existing = Customer.query.filter_by(
        first_name=first_name, 
        last_name=last_name, 
        contact_number=contact_number
    ).first()
    
    if existing:
        flash(f"A customer named {first_name} {last_name} with this contact number already exists.", "warning")
        return redirect(request.referrer or url_for('admin.customers'))

    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'ids')
    os.makedirs(upload_folder, exist_ok=True)

    def save_id_file(file):
        if not file or file.filename == '':
            return None
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        return f"uploads/ids/{filename}"

    valid_id_file = request.files.get('valid_id')
    secondary_id_file = request.files.get('secondary_id')
    proof_of_billing_file = request.files.get('proof_of_billing')

    valid_id_path = save_id_file(valid_id_file)
    secondary_id_path = save_id_file(secondary_id_file)
    proof_of_billing_path = save_id_file(proof_of_billing_file)

    new_customer = Customer(
        user_id=None, 
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        contact_number=contact_number,
        secondary_contact_number=secondary_contact_number,
        home_address=home_address,
        primary_id_type=primary_id_type,
        secondary_id_type=secondary_id_type,
        valid_id_path=valid_id_path,
        secondary_id_path=secondary_id_path,
        proof_of_billing_path=proof_of_billing_path, 
        id_uploaded_at=datetime.utcnow(),
        is_id_verified=True if valid_id_path else False,
        created_by_id=current_user.id,
        is_active=True 
    )

    try:
        db.session.add(new_customer)
        
        log = InventoryLog(
            action="Admin Created Customer",
            note=f"Customer {first_name} {last_name} added manually by {current_user.email}",
            user_id=current_user.id,
            user_name=f"{current_user.first_name} {current_user.last_name}"
        )
        db.session.add(log)
        
        db.session.commit()
        flash(f"Customer {new_customer.full_name} added successfully!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Customer Creation Error: {str(e)}")
        flash("A database error occurred. Please try again.", "error")

    return redirect(url_for('admin.customers'))

@admin_bp.route('/update-customer', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_customers')
def update_customer():
    customer_id = request.form.get("customer_id")
    customer = Customer.query.options(db.joinedload(Customer.user)).get_or_404(customer_id)

    first_name = request.form.get("first_name", "").strip().title()
    last_name = request.form.get("last_name", "").strip().title()
    
    if first_name:
        customer.first_name = first_name
        if customer.user: customer.user.first_name = first_name
    if last_name:
        customer.last_name = last_name
        if customer.user: customer.user.last_name = last_name

    gender = request.form.get("gender", "").strip().capitalize()
    if gender:
        customer.gender = gender

    customer.home_address = request.form.get("home_address", "").strip().title()
    customer.contact_number = request.form.get("contact_number", "").strip()
    customer.secondary_contact_number = request.form.get("secondary_contact_number", "").strip()

    if "is_active" in request.form:
        is_active_val = request.form.get("is_active") == "on"
        if customer.is_active != is_active_val:
            customer.is_active = is_active_val
            if customer.user:
                customer.user.is_active = is_active_val 

    def handle_id(file_key, path_attr, remove_flag_name=None, subfolder="ids", prefix="ID"):
        remove_flag = request.form.get(remove_flag_name) if remove_flag_name else None
        image_file = request.files.get(file_key)
        old_path = getattr(customer, path_attr, None)

        if remove_flag == "true" and old_path:
            full_path = os.path.join(current_app.root_path, 'static', old_path)
            if os.path.exists(full_path):
                os.remove(full_path)
            setattr(customer, path_attr, None)

        elif image_file and image_file.filename:
            ext = os.path.splitext(image_file.filename)[1].lower()
            filename = f"{prefix}_{uuid.uuid4().hex[:12]}{ext}"
            relative_path = f"uploads/{subfolder}/{filename}"
            absolute_path = os.path.join(current_app.root_path, 'static', 'uploads', subfolder)
            
            os.makedirs(absolute_path, exist_ok=True)
            
            if old_path:
                old_full = os.path.join(current_app.root_path, 'static', old_path)
                if os.path.exists(old_full):
                    os.remove(old_full)

            image_file.save(os.path.join(absolute_path, filename))
            setattr(customer, path_attr, relative_path)
            if file_key == "valid_id":
                customer.id_uploaded_at = datetime.utcnow()

    handle_id("valid_id", "valid_id_path", "remove_valid_id", "ids", "ID")
    handle_id("secondary_id", "secondary_id_path", "remove_secondary_id", "ids", "ID")
    handle_id("proof_of_billing", "proof_of_billing_path", None, "billing", "BILLING")

    customer.primary_id_type = request.form.get("primary_id_type", "").strip()
    customer.secondary_id_type = request.form.get("secondary_id_type", "").strip()

    if "is_id_verified" in request.form:
        customer.is_id_verified = request.form.get("is_id_verified") == "on"

    try:
        audit_log = InventoryLog(
            action="Admin Updated Customer",
            note=f"Customer ID {customer.id} updated by {current_user.first_name}",
            user_id=current_user.id,
            user_name=current_user.full_name
        )
        db.session.add(audit_log)
        
        db.session.commit()
        flash(f"Profile for {customer.full_name} updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update Error: {e}")
        flash("An error occurred while saving changes.", "error")

    return redirect(url_for("admin.customers"))

@admin_bp.route('/products')
@limiter.exempt
@login_required
@admin_or_staff_required
@permission_required('can_manage_products')
def products():
    page           = request.args.get('page', 1, type=int)
    limit          = request.args.get('limit', 10, type=int)
    search_query   = request.args.get('q', '').strip()
    equipment_type = request.args.get('type', 'all')
    filter_type    = request.args.get('filter', '')         
 
    query = Product.query.filter(Product.status != 'Archived')
 
    if search_query:
        query = query.filter(or_(
            Product.equipment_type.ilike(f"%{search_query}%"),
            Product.name.ilike(f"%{search_query}%")
        ))
 
    if equipment_type and equipment_type != 'all':
        query = query.filter(Product.equipment_type.ilike(f"%{equipment_type}%"))
 
    # ── filter deep-links from notifications ──────────────────────────────
    if filter_type == 'low_stock':
        query = query.filter(
            Product.stock <= Product.reorder_level,
            Product.stock > 0,
            Product.status != 'Archived'
        )
    elif filter_type == 'out_of_stock':
        query = query.filter(
            Product.stock == 0,
            Product.status != 'Archived'
        )
    # ─────────────────────────────────────────────────────────────────────
 
    pagination = query.order_by(
        Product.equipment_type.asc(),
        Product.name.asc()
    ).paginate(page=page, per_page=limit, error_out=False)
 
    start_entry = 0
    end_entry   = 0
    if pagination.total > 0:
        start_entry = (pagination.page - 1) * pagination.per_page + 1
        end_entry   = min(pagination.page * pagination.per_page, pagination.total)
 
    stats = {
        'total_inventory':    db.session.query(func.sum(Product.stock)).scalar() or 0,
        'low_stock_count':    Product.query.filter(
            Product.stock <= Product.reorder_level,
            Product.stock > 0,
            Product.status != 'Archived'
        ).count(),
        'available_for_rent': Product.query.filter_by(status='Available').count()
    }
 
    customers = Customer.query.filter_by(is_active=True)\
        .order_by(Customer.last_name.asc()).all()
        
    # Dynamic equipment types from actual inventory
    equipment_types = db.session.query(
        Product.equipment_type
    ).filter(
        Product.equipment_type != None,
        Product.status != 'Archived'
    ).distinct().order_by(Product.equipment_type.asc()).all()
    equipment_types = [et[0] for et in equipment_types]
 
    return render_template(
        "admin/products.html",
        products=pagination.items,
        pagination=pagination,
        customers=customers,
        search_query=search_query,
        current_limit=limit,
        current_type=equipment_type,
        current_filter=filter_type,      
        start_entry=start_entry,
        end_entry=end_entry,
        equipment_types=equipment_types,
        **stats
    )

@admin_bp.route('/add-product', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_products')
def add_product():
    equipment_type = request.form.get("equipment_type", "").strip().title()
    name = request.form.get("name", "").strip().title()
    size = request.form.get("size", "").strip()
    description = request.form.get("description", "").strip()
    
    is_refillable = True if request.form.get("is_refillable") == "on" else False

    if "oxygen" in equipment_type.lower() or "oxygen" in name.lower():
        is_refillable = True
    
    transaction_type = request.form.get("offer_type", "Sale").strip().title()
    rent_period = request.form.get("rent_period", "Monthly").strip().title()
    condition = request.form.get("condition", "Brand New").strip()

    try:
        stock = int(request.form.get("stock", 0))
        default_reorder = int(SystemSetting.value_of("default_reorder_level") or 5)
        reorder_level = int(request.form.get("reorder_level") or default_reorder)
        rent_price_raw = request.form.get("rent_price", "").strip()
        sale_price_raw = request.form.get("sale_price", "").strip()
        cost_price_raw = request.form.get("cost_price", "").strip()

        if transaction_type == 'Rental':
            rent_price = Decimal(rent_price_raw) if rent_price_raw else Decimal("0.00")
            sale_price = Decimal("0.00")
        elif transaction_type == 'Sale':
            sale_price = Decimal(sale_price_raw) if sale_price_raw else Decimal("0.00")
            rent_price = Decimal("0.00")
        else:
            rent_price = Decimal(rent_price_raw) if rent_price_raw else Decimal("0.00")
            sale_price = Decimal(sale_price_raw) if sale_price_raw else Decimal("0.00")

        cost_price = Decimal(cost_price_raw) if cost_price_raw else Decimal("0.00")
        
        if transaction_type == 'Rental' and rent_price <= 0:
            flash("Please provide a valid rent price for 'Rent Only' items.", "warning")
            return redirect(request.referrer)
        if transaction_type == 'Sale' and sale_price <= 0:
            flash("Please provide a valid sale price for 'Sale Only' items.", "warning")
            return redirect(request.referrer)
        
        if stock < 0:
            raise ValueError("Stock cannot be negative.")
        if reorder_level < 0:
            raise ValueError("Reorder level cannot be negative.")
        
    except (ValueError, InvalidOperation):
        flash("Oops! Please double-check the stock and price fields. Ensure you've entered valid numbers.", "error")
        return redirect(request.referrer)

    if not equipment_type:
        flash("The 'Equipment Type' is required. Please fill it out and try again.", "warning")
        return redirect(request.referrer)

    image_file = request.files.get("image")
    image_path = None
    
    if image_file and image_file.filename != '':
        ext = os.path.splitext(secure_filename(image_file.filename))[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            flash("Invalid image format. Please use JPG, PNG, or WebP files.", "error")
            return redirect(request.referrer)
            
        random_name = f"prod_{uuid.uuid4().hex[:12]}{ext}"
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
        os.makedirs(upload_folder, exist_ok=True)
        
        image_path = f"uploads/products/{random_name}"
        full_path = os.path.join(upload_folder, random_name)
        
        try:
            image_file.save(full_path)
        except Exception as e:
            current_app.logger.error(f"Image Save Error: {e}")
            flash("We had trouble saving the product image. Please try uploading it again.", "error")
 
    try:
        new_product = Product(
            equipment_type=equipment_type,
            name=name,
            size=size, 
            description=description, 
            stock=stock,
            reorder_level=reorder_level,
            is_refillable=is_refillable,
            transaction_type=transaction_type,    
            rent_period=rent_period,    
            rent_price=rent_price,
            sale_price=sale_price,
            cost_price=cost_price, 
            condition=condition,   
            image=image_path,
            status="Available" if stock > 0 else "Out of Stock"
        )
        
        db.session.add(new_product)
        db.session.flush() 

        if is_refillable:
            new_tank_status = TankStatus(
                product_id=new_product.id,
                total_owned=stock,
                full_in_stock=stock, 
                empty_in_stock=0,
                rented_out=0
            )
            db.session.add(new_tank_status)

        log = InventoryLog(
            product_id=new_product.id,
            reference_no=f"PRD-{new_product.id:05d}",
            reason_code="OPENING",
            action="Initial Stock Entry",
            quantity=stock,
            balance_after=stock,
            note=f"Registered {name} (Size: {size}). Mode: {transaction_type}. Refillable: {is_refillable}. Condition: {condition}. Cost: {cost_price}",
            user_id=current_user.id,
            user_name=current_user.full_name 
        )
        db.session.add(log)

        if cost_price and cost_price > 0 and stock > 0:
            acq_category = get_cogs_category(new_product)
            acq_amount = (cost_price * stock).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            db.session.add(Expense(
                category=acq_category,
                expense_title=f"Stock Acquisition — {name} x{stock}",
                amount=acq_amount,
                description=f"Auto-recorded on initial stock entry. "
                            f"Unit cost: ₱{cost_price:,.2f} × {stock} unit(s).",
                date_incurred=datetime.utcnow().date(),
                recorded_by_id=current_user.id,
                product_id=new_product.id,
            ))
        elif stock > 0 and (not cost_price or cost_price == 0):
            db.session.add(InventoryLog(
                product_id=new_product.id,
                action="Acquisition Warning",
                note=f"Cost price not set for '{name}' — no acquisition expense recorded.",
                user_id=current_user.id,
                user_name=current_user.full_name
            ))
        
        db.session.commit()
        flash(f"Success! '{name}' has been added to your inventory.", "success")
        
    except Exception as e:
        db.session.rollback()
        if image_path:
            abs_image_path = os.path.join(current_app.root_path, "static", image_path)
            if os.path.exists(abs_image_path):
                os.remove(abs_image_path)
        
        current_app.logger.error(f"Database Error on Product Add: {str(e)}")
        flash("Something went wrong on our end while saving. Please wait a moment and try again.", "error")

    return redirect(url_for('admin.products'))

@admin_bp.route('/edit-product/<int:product_id>', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_products')
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    new_type = request.form.get("equipment_type", "").strip().title()
    new_name = request.form.get("name", "").strip().title()
    new_size = request.form.get("size", "").strip() 
    new_description = request.form.get("description", "").strip()
    new_condition = request.form.get("condition", "").strip()
    
    new_offer_type = request.form.get("offer_type", "Rental").strip().title()
    new_rent_period = request.form.get("rent_period", "Monthly").strip().title()
    
    if not new_type or not new_name:
        flash("Equipment Type and Product Name are required fields.", "warning")
        return redirect(url_for('admin.products'))

    changes = []

    try:
        raw_rent = Decimal(request.form.get("rent_price") or "0.00")
        raw_sale = Decimal(request.form.get("sale_price") or "0.00")
        new_reorder = int(
            request.form.get("reorder_level")
            or SystemSetting.value_of("default_reorder_level")
            or 5
        )
        if new_reorder < 0:
            raise ValueError("Reorder level cannot be negative.")

        new_rent = raw_rent if new_offer_type in ['Both', 'Rental'] else Decimal("0.00")
        new_sale = raw_sale if new_offer_type in ['Both', 'Sale'] else Decimal("0.00")

        if product.transaction_type != new_offer_type:
            changes.append(f"Changed type from '{product.transaction_type}' to '{new_offer_type}'")
            product.transaction_type = new_offer_type

        if product.rent_period != new_rent_period:
            changes.append(f"Updated rental period to '{new_rent_period}'")
            product.rent_period = new_rent_period

        if product.equipment_type != new_type:
            changes.append(f"Updated type to '{new_type}'")
            product.equipment_type = new_type

        if (product.name or "") != new_name:
            changes.append(f"Renamed to '{new_name}'")
            product.name = new_name
            
        if (product.size or "") != new_size:
            changes.append(f"Updated size from '{product.size or 'N/A'}' to '{new_size}'")
            product.size = new_size

        if (product.description or "").strip() != new_description:
            changes.append("Updated description")
            product.description = new_description

        if product.condition != new_condition:
            changes.append(f"Changed condition to '{new_condition}'")
            product.condition = new_condition

        if product.rent_price != new_rent:
            changes.append(f"Changed rental rate to ₱{new_rent:,.2f}")
            product.rent_price = new_rent

        if product.sale_price != new_sale:
            changes.append(f"Changed sale price to ₱{new_sale:,.2f}")
            product.sale_price = new_sale

        if (product.reorder_level or 0) != new_reorder:
            changes.append(
                f"Changed reorder level from {product.reorder_level or 0} to {new_reorder}"
            )
            product.reorder_level = new_reorder

    except (ValueError, InvalidOperation):
        flash("Oops! Please double-check your pricing fields. Ensure you've entered valid numbers.", "error")
        return redirect(url_for('admin.products'))

    # Image Handling
    image_file = request.files.get("image")
    if image_file and image_file.filename != '':
        ext = os.path.splitext(secure_filename(image_file.filename))[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            flash("Invalid image format. Please use JPG, PNG, or WebP.", "error")
            return redirect(url_for('admin.products'))

        if product.image:
            old_full_path = os.path.join(current_app.root_path, "static", product.image)
            if os.path.exists(old_full_path):
                os.remove(old_full_path)

        random_name = f"prod_{uuid.uuid4().hex[:12]}{ext}"
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "products")
        os.makedirs(upload_folder, exist_ok=True)
        
        image_file.save(os.path.join(upload_folder, random_name))
        product.image = f"uploads/products/{random_name}"
        changes.append("Updated product image")

    try:
        if changes:
            inventory_log = InventoryLog(
                product_id=product.id,
                action="Product Edited",
                quantity=product.stock,
                note=f"{'; '.join(changes)}",
                user_id=current_user.id,
                user_name=current_user.full_name
            )
            db.session.add(inventory_log)
            db.session.commit()
            flash(f"Success! The details for '{product.name}' have been updated.", "success")
        else:
            flash("No changes were detected.", "info")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Product Update Error: {e}")
        flash("Something went wrong on our end while updating. Please try again.", "error")

    return redirect(url_for('admin.products'))

@admin_bp.route('/update_stock/<int:product_id>', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_products')
@csrf.exempt
def update_stock(product_id):

    data = request.get_json() or {}
    product = Product.query.get_or_404(product_id)

    try:
        increment = int(data.get('increment', 0))
        reason = data.get('reason', '').strip() or 'Stock replenishment'
        total_amount_paid = data.get('total_amount_paid', None)
        if total_amount_paid is not None:
            total_amount_paid = Decimal(str(total_amount_paid)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
    except (ValueError, TypeError, Exception):
        return jsonify({
            "success": False,
            "message": "Invalid quantity or amount format."
        }), 400

    if increment <= 0:
        return jsonify({
            "success": False,
            "message": "Increment must be at least 1 unit."
        }), 400

    try:
        old_stock = product.stock
        product.stock += increment
        product.status = "Available" if product.stock > 0 else "Out of Stock"

        # ── Sync TankStatus for refillable products ────────────────────────
        if product.is_refillable and product.tank_status:
            product.tank_status.full_in_stock = (product.tank_status.full_in_stock or 0) + increment
            product.tank_status.total_owned = (
                (product.tank_status.full_in_stock or 0) +
                (product.tank_status.empty_in_stock or 0) +
                (product.tank_status.rented_out or 0)
            )

        # ── Auto-update unit cost if total amount paid is provided ─────────
        if total_amount_paid and total_amount_paid > 0:
            new_unit_cost = (total_amount_paid / increment).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            product.cost_price = new_unit_cost

        log_note = (
            f"Restocked: {old_stock} → {product.stock}. "
            f"Reason: {reason}"
        )
        if total_amount_paid:
            log_note += f". Total paid: ₱{total_amount_paid:,.2f}"

        db.session.add(InventoryLog(
            product_id=product.id,
            reason_code="RESTOCK",
            action="Restock",
            quantity=increment,
            balance_after=product.stock,
            note=log_note[:255],
            user_id=current_user.id,
            user_name=current_user.full_name
        ))

        # ── Auto restock expense ───────────────────────────────────────────
        expense_amount = total_amount_paid if (total_amount_paid and total_amount_paid > 0) else (
            (product.cost_price * increment).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if product.cost_price and product.cost_price > 0 else None
        )

        if expense_amount and expense_amount > 0:
            restock_category = get_cogs_category(product)
            unit_cost_display = product.cost_price or (total_amount_paid / increment)
            db.session.add(Expense(
                category=restock_category,
                expense_title=f"Restock — {product.name} x{increment}",
                amount=expense_amount,
                description=f"Auto-recorded on restock. "
                            f"Unit cost: ₱{unit_cost_display:,.2f} × {increment} unit(s).",
                date_incurred=datetime.utcnow().date(),
                recorded_by_id=current_user.id,
                product_id=product.id,
            ))
        else:
            db.session.add(InventoryLog(
                product_id=product.id,
                action="Acquisition Warning",
                note=f"No cost provided for restock of '{product.name}' — no expense recorded.",
                user_id=current_user.id,
                user_name=current_user.full_name
            ))

        db.session.commit()

        return jsonify({
            "success": True,
            "new_stock": product.stock,
            "new_status": product.status,
            "new_unit_cost": float(product.cost_price) if product.cost_price else 0,
            "message": (
                f"Added {increment} units. "
                f"Total stock for {product.name} is now {product.stock}."
                + (f" Unit cost updated to ₱{product.cost_price:,.2f}." if total_amount_paid else "")
            )
        })

    except Exception:
        db.session.rollback()
        current_app.logger.exception(f"Stock Update Error for Product {product_id}")
        return jsonify({
            "success": False,
            "message": "Unable to update inventory at this time."
        }), 500

     
@admin_bp.route('/delete-product/<int:product_id>', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_manage_products')
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    try:
        has_active_rentals = Rental.query.filter(
            Rental.product_id == product.id,
            Rental.status.in_(["Active", "Overdue"])
        ).first()

        if has_active_rentals:
            flash(f"Cannot archive '{product.name}' due to active rentals.", "warning")
            return redirect(url_for('admin.products'))

        product.status = "Archived"
        product.stock = 0

        if hasattr(product, "is_active"):
            product.is_active = False

        if hasattr(product, "archived_at"):
            product.archived_at = datetime.utcnow()

        db.session.add(InventoryLog(
            product_id=product.id,
            action="ARCHIVE",
            quantity=0,
            note=f"Archived by {current_user.full_name}",
            user_id=current_user.id,
            user_name=current_user.full_name
        ))

        db.session.commit()

        flash(f"Product '{product.name}' archived successfully.", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"ARCHIVE_ERROR: {str(e)}")
        flash("Failed to archive product.", "danger")

    return redirect(url_for('admin.products'))

@admin_bp.route('/process-purchase', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_process_transactions')
def process_purchase():
    from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
    
    try:
        try:
            raw_amount_paid = request.form.get('amount_paid')
            if isinstance(raw_amount_paid, list):
                raw_amount_paid = raw_amount_paid[0]
            amount_paid = Decimal(str(raw_amount_paid or request.form.get('paid_amount') or '0.00'))
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for amount paid.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        try:
            raw_voucher = request.form.get('voucher_amount') or request.form.get('voucher') or request.form.get('discount') or '0.00'
            if isinstance(raw_voucher, list):
                raw_voucher = raw_voucher[0]
            voucher_amount = Decimal(str(raw_voucher))
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for voucher amount.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        if voucher_amount < 0:
            flash("Voucher or discount amount cannot be negative.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        buyer_type = request.form.get('buyer_type', 'registered')
        if isinstance(buyer_type, list):
            buyer_type = buyer_type[0]
            
        customer_id = request.form.get('customer_id')
        if isinstance(customer_id, list):
            customer_id = customer_id[0]

        customer_name_raw = request.form.get('unregistered_customer_name') or request.form.get('customer_name') or ''
        if isinstance(customer_name_raw, list):
            customer_name_raw = customer_name_raw[0]
        customer_name = customer_name_raw.strip()

        if buyer_type == 'registered':
            if not customer_id:
                flash("Registered customer selection is required.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))
            
            customer = db.session.get(Customer, int(customer_id))
            if not customer:
                flash("Selected customer profile not found.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            customer_name = customer.full_name
        else:
            if not customer_name:
                flash("Walk-In Buyer / Patient full name is required.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))
            customer_id = None

        items_data = request.form.get('items', [])
        if isinstance(items_data, list) and len(items_data) == 1 and isinstance(items_data[0], str):
            try:
                items_data = json.loads(items_data[0])
            except (json.JSONDecodeError, TypeError):
                pass

        if isinstance(items_data, str):
            try:
                items_data = json.loads(items_data)
            except (json.JSONDecodeError, TypeError):
                flash("Failed to decode basket collection elements.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

        if not items_data or not isinstance(items_data, list):
            flash("Please select at least one item to purchase.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        now = datetime.now()
        ref_no = f"PUR-{now:%m%d%Y}-{now:%H%M%S}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
        
        fulfillment_raw = request.form.get("fulfillment_type", "Walk-In")
        if isinstance(fulfillment_raw, list):
            fulfillment_raw = fulfillment_raw[0]
        fulfillment = fulfillment_raw

        delivery_addr_raw = request.form.get("delivery_address")
        if isinstance(delivery_addr_raw, list):
            delivery_addr_raw = delivery_addr_raw[0]
            
        landmark_raw = request.form.get("landmark")
        if isinstance(landmark_raw, list):
            landmark_raw = landmark_raw[0]

        transaction_status = "Closed" if fulfillment == "Walk-In" else "Open"

        new_transaction = Transaction(
            reference_no=ref_no,
            customer_id=customer_id,
            customer_name=customer_name,
            processed_by=current_user.id,
            transaction_type="Sale",
            total_amount=Decimal("0.00"),
            voucher_amount=voucher_amount,
            fulfillment_type=fulfillment,
            delivery_address=delivery_addr_raw if fulfillment == "Delivery" else None,
            landmark=landmark_raw if fulfillment == "Delivery" else None,
            delivery_status="Pending" if fulfillment == "Delivery" else "N/A",
            tracking_status="SUBMITTED",
            status=transaction_status  
        )

        db.session.add(new_transaction)
        db.session.flush() 

        for item in items_data:
            try:
                product_id = int(item.get('id'))
                quantity = int(item.get('quantity', 1))
                unit_price = Decimal(str(item.get('price', '0.00')))
            except (ValueError, TypeError, InvalidOperation):
                db.session.rollback()
                flash("Invalid numeric values detected inside basket components.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if quantity <= 0:
                db.session.rollback()
                flash("Quantity must be at least 1 for all selected products.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            product = Product.query.filter_by(id=product_id).with_for_update().first()

            if not product:
                db.session.rollback()
                flash(f"Product entry unique ID {product_id} is unavailable.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if not product.is_active:
                db.session.rollback()
                flash(f"'{product.name}' has been archived.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if product.stock < quantity:
                db.session.rollback()
                flash(f"Only {product.stock} units left in stock for '{product.name}'.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            item_total_price = (unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            product.stock -= quantity

            if product.stock <= 0:
                product.stock = 0
                product.status = "Out of Stock"
            else:
                product.status = "Available"
                
            if product.is_refillable and product.tank_status:
                product.tank_status.full_in_stock = max(
                    (product.tank_status.full_in_stock or 0) - quantity, 0
                )
                product.tank_status.total_owned = max(
                    (product.tank_status.total_owned or 0) - quantity, 0
                )

            notes_raw = request.form.get("warranty_or_notes", "")
            if isinstance(notes_raw, list):
                notes_raw = notes_raw[0]

            db.session.add(Purchase(
                transaction_id=new_transaction.id,
                product_id=product.id,
                customer_id=customer_id,  
                quantity=quantity,
                unit_price=unit_price,
                total_price=item_total_price,
                warranty_or_notes=(notes_raw or "").strip(),
                product_name=product.name,
                product_asset_tag=product.asset_tag,
                product_type=getattr(product, 'equipment_type', None) or getattr(product, 'product_type', None),
                product_description=product.description,
                product_image=product.image,
                product_condition=product.condition,
                product_category=product.category,
                product_cost_price=product.cost_price,
                product_sale_price=product.sale_price,
                product_rent_price=product.rent_price,
                product_rent_period=product.rent_period
            ))

            db.session.add(InventoryLog(
                product_id=product.id,
                transaction_id=new_transaction.id,
                reference_no=ref_no,
                reason_code="SALE",
                action="SALE",
                quantity=-quantity,
                balance_after=product.stock,
                note=f"Sold {quantity} via {ref_no}",
                user_id=current_user.id,
                user_name=getattr(current_user, 'full_name', 'System Administrator')
            ))

        if amount_paid > 0:
            pm_raw = request.form.get("payment_method", "Cash")
            if isinstance(pm_raw, list):
                pm_raw = pm_raw[0]
            payment_method = (pm_raw or "Cash").strip()
            
            ref_num_raw = request.form.get("reference_number", "")
            if isinstance(ref_num_raw, list):
                ref_num_raw = ref_num_raw[0]
            reference_number = (ref_num_raw or "").strip()

            if payment_method.lower() == "cash":
                reference_number = None
            else:
                if not reference_number:
                    db.session.rollback()
                    flash("Reference number is required for non-cash payments.", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

                existing_payment = Payment.query.filter_by(
                    reference_number=reference_number
                ).first()

                if existing_payment:
                    db.session.rollback()
                    flash("Payment reference number already exists.", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

            new_transaction.payment_method = payment_method

            db.session.add(Payment(
                transaction_id=new_transaction.id,
                invoice_id=None,
                payment_type="Sale",
                amount=amount_paid,
                payment_method=payment_method,
                reference_number=reference_number,
                status="Completed",
                verified_by_id=current_user.id,
                verified_at=datetime.utcnow()
            ))

        new_transaction.update_totals()
            
        db.session.commit()
        flash(f"Purchase created: {ref_no}", "success")
        return redirect(url_for("admin.transactions"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PURCHASE_ERROR: {str(e)}")
        flash("Purchase processing failed.", "danger")
        return redirect(request.referrer or url_for('admin.transactions'))
    
@admin_bp.route('/process-rental', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_process_transactions')
def process_rental():
    from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
    
    try:
        product_ids = (
            request.form.getlist('product_ids') or 
            request.form.getlist('product_id[]') or 
            request.form.getlist('product_id')
        )

        if not product_ids:
            flash("No products selected.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        fulfillment_type = request.form.get('fulfillment_type', 'Walk-In')
        if isinstance(fulfillment_type, list):
            fulfillment_type = fulfillment_type[0]

        try:
            raw_amount_paid = request.form.get('amount_paid')
            if isinstance(raw_amount_paid, list):
                raw_amount_paid = raw_amount_paid[0]
            amount_paid = Decimal(str(raw_amount_paid or request.form.get('paid_amount') or '0').replace(',', '') or '0')
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for amount paid.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        if amount_paid < 0:
            flash("Amount paid cannot be negative.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        try:
            raw_customer_deposit = request.form.get('customer_deposit')
            if isinstance(raw_customer_deposit, list):
                raw_customer_deposit = raw_customer_deposit[0]
            customer_deposit = Decimal(str(raw_customer_deposit or '0').replace(',', '') or '0')
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for customer deposit.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        if customer_deposit < 0:
            flash("Customer deposit cannot be negative.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        # FR02 / RULE-03: delivery deposits are derived from the owner-configured
        # distance tiers. The flat amount remains a fallback for legacy/blank tiers.
        distance_km = None
        deposit_rule = None
        if fulfillment_type == 'Delivery':
            raw_distance = request.form.get('distance_km')
            if isinstance(raw_distance, list):
                raw_distance = raw_distance[0]
            try:
                distance_km = Decimal(str(raw_distance or '').replace(',', ''))
            except (ValueError, TypeError, InvalidOperation):
                flash("Please enter the delivery distance in kilometres.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))
            if distance_km <= 0:
                flash("Delivery distance must be greater than zero.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            try:
                deposit_tiers = parse_deposit_tiers(
                    SystemSetting.value_of('deposit_distance_tiers')
                )
            except ValueError:
                deposit_tiers = []
                current_app.logger.warning(
                    "Invalid deposit_distance_tiers setting; using flat fallback."
                )

            customer_deposit, deposit_rule = resolve_delivery_deposit(
                distance_km,
                tiers=deposit_tiers,
                fallback_amount=SystemSetting.value_of('deposit_flat_amount'),
            )
            customer_deposit = customer_deposit.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        try:
            raw_voucher = request.form.get('voucher_amount') or request.form.get('voucher') or request.form.get('discount') or '0'
            if isinstance(raw_voucher, list):
                raw_voucher = raw_voucher[0]
            voucher_amount = Decimal(str(raw_voucher).replace(',', '') or '0')
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for voucher amount.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        if voucher_amount < 0:
            flash("Voucher or discount amount cannot be negative.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        try:
            raw_delivery_fee = request.form.get('delivery_fee', '0')
            if isinstance(raw_delivery_fee, list):
                raw_delivery_fee = raw_delivery_fee[0]
            delivery_fee = Decimal(str(raw_delivery_fee).replace(',', '') or '0')
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for delivery fee.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        has_initial_fill = True if request.form.get('has_initial_fill') in ['on', 'true', '1', True] else False
        
        try:
            initial_fill_cost_raw = request.form.get('initial_fill_cost', '0')
            if isinstance(initial_fill_cost_raw, list):
                initial_fill_cost_raw = initial_fill_cost_raw[0]
            initial_fill_cost = Decimal(str(initial_fill_cost_raw).replace(',', '') or '0')
        except (ValueError, TypeError, InvalidOperation):
            flash("Invalid numeric input for initial fill cost.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        start_date_str = request.form.get('start_date')
        if isinstance(start_date_str, list):
            start_date_str = start_date_str[0]
            
        return_date_str = request.form.get('return_date')
        if isinstance(return_date_str, list):
            return_date_str = return_date_str[0]
            
        duration_unit = request.form.get('duration_unit', 'months')
        if isinstance(duration_unit, list):
            duration_unit = duration_unit[0]

        if not start_date_str:
            flash("Start date is required.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid start date format.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        if duration_unit == 'open':
            expected_return = start_date + timedelta(days=30) 
            is_open_duration = True
        else:
            is_open_duration = False
            if not return_date_str:
                flash("Return date is required for fixed-term rentals.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))
            try:
                expected_return = datetime.strptime(return_date_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid return date format.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if expected_return < start_date:
                flash("Invalid return date.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

        customer_id = request.form.get('customer_id') or None
        if isinstance(customer_id, list):
            customer_id = customer_id[0]
            
        display_name = "Walk-in Customer"

        if customer_id:
            customer = db.session.get(Customer, int(customer_id))
            if customer:
                display_name = customer.full_name
        else:
            unregistered_name_raw = request.form.get('unregistered_customer_name', '')
            if isinstance(unregistered_name_raw, list):
                unregistered_name_raw = unregistered_name_raw[0]
            unregistered_name = unregistered_name_raw.strip()
            if unregistered_name:
                display_name = unregistered_name

        now = datetime.now()
        ref_no = f"RNT-{now:%m%d%Y-%H%M%S}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"

        new_txn = Transaction(
            reference_no=ref_no,
            customer_id=int(customer_id) if customer_id else None,
            customer_name=display_name,
            processed_by=current_user.id,
            transaction_type="Rental",
            total_amount=Decimal("0.00"),
            voucher_amount=voucher_amount,
            delivery_fee=delivery_fee,
            fulfillment_type=fulfillment_type,
            has_initial_fill=has_initial_fill,
            initial_fill_cost=initial_fill_cost,
            deposit_amount=customer_deposit,
            distance_km=distance_km,
            deposit_rule=deposit_rule,
            status="Open"
        )

        db.session.add(new_txn)
        db.session.flush()

        rentals = []

        for i, pid in enumerate(product_ids):
            product = Product.query.filter_by(id=int(pid)).with_for_update().first()
            if not product:
                db.session.rollback()
                flash(f"Product ID {pid} not found.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if not product.is_active:
                db.session.rollback()
                flash(f"'{product.name}' has been archived.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            qty_raw = (
                request.form.get(f'quantity_{product.id}') or 
                (request.form.getlist('quantity[]')[i] if i < len(request.form.getlist('quantity[]')) else None) or
                (request.form.getlist('quantity')[i] if i < len(request.form.getlist('quantity')) else '1')
            )
            if isinstance(qty_raw, list):
                qty_raw = qty_raw[0]
            try:
                qty = int(qty_raw or 1)
            except (ValueError, TypeError):
                qty = 1

            price_raw = (
                request.form.get(f'unit_price_{product.id}') or 
                (request.form.getlist('unit_price[]')[i] if i < len(request.form.getlist('unit_price[]')) else None) or
                (request.form.getlist('unit_price')[i] if i < len(request.form.getlist('unit_price')) else str(product.rent_price))
            )
            if isinstance(price_raw, list):
                price_raw = price_raw[0]
            try:
                price = Decimal(str(price_raw or product.rent_price or '0').replace(',', '') or '0')
            except (ValueError, TypeError, InvalidOperation):
                price = Decimal('0.00')

            if qty <= 0:
                db.session.rollback()
                flash(f"Invalid quantity for {product.name}", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            product_name_lower = (product.name or "").lower()
            product_cat_lower = (product.category or "").lower()
            is_oxygen = (
                "oxygen" in product_name_lower or 
                "o2" in product_name_lower or 
                "concentrator" in product_name_lower or 
                "oxygen" in product_cat_lower
            )

            serials = []
            if is_oxygen:
                for j in range(qty):
                    serial_val = request.form.get(f'serial_number_{product.id}_{j}')
                    if isinstance(serial_val, list):
                        serial_val = serial_val[0]
                    if serial_val and serial_val.strip():
                        serials.append(serial_val.strip())

            if product.is_refillable:
                if not product.tank_status:
                    db.session.rollback()
                    flash(f"Tank status not configured for {product.name}", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

                available = product.tank_status.full_in_stock or 0
                if available < qty:
                    db.session.rollback()
                    flash(f"Not enough available tanks for {product.name}. Available: {available}", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

                product.tank_status.rented_out = (product.tank_status.rented_out or 0) + qty
                product.tank_status.full_in_stock = max((product.tank_status.full_in_stock or 0) - qty, 0)
                log_note = f"Rental created (Tank metrics updated) {ref_no}"
            else:
                if hasattr(product, 'stock') and product.stock is not None:
                    if product.stock < qty:
                        db.session.rollback()
                        flash(f"Not enough stock available for {product.name}. Available: {product.stock}", "danger")
                        return redirect(request.referrer or url_for('admin.transactions'))
                    
                    product.stock -= qty
                    if product.stock <= 0:
                        product.stock = 0
                        product.status = "Out of Stock"
                    else:
                        product.status = "Available"
                log_note = f"Rental created (Standard asset stock deducted) {ref_no}"

            rental = Rental(
                transaction_id=new_txn.id,
                product_id=product.id,
                customer_id=new_txn.customer_id,
                start_date=start_date,
                expected_return_date=expected_return,
                monthly_rate=price,
                quantity=qty,
                status="Active",
                is_open_duration=is_open_duration 
            )

            db.session.add(rental)
            db.session.flush() 

            for s_val in serials:
                rental_tank = RentalTank(
                    rental_id=rental.id,
                    serial_number=s_val,
                    status="Active"
                )
                db.session.add(rental_tank)

            rentals.append(rental)

            db.session.add(InventoryLog(
                product_id=product.id,
                transaction_id=new_txn.id,
                reference_no=ref_no,
                reason_code="RENTAL",
                action="RENTAL",
                quantity=qty if not product.is_refillable else 0,
                balance_after=(
                    product.tank_status.full_in_stock
                    if product.tank_status else product.stock
                ),
                note=log_note,
                user_id=current_user.id,
                user_name=getattr(current_user, 'full_name', 'System Administrator')
            ))

        db.session.flush()

        for r in rentals:
            r.generate_monthly_invoices()

        db.session.flush()

        all_invoices = []
        for r in rentals:
            for inv in r.invoices:
                all_invoices.append(inv)

        new_txn.update_totals() 
        db.session.expire(new_txn, ['payments'])

        pm_raw = request.form.get('payment_method', 'Cash')
        if isinstance(pm_raw, list):
            pm_raw = pm_raw[0]
        payment_method = (pm_raw or 'Cash').strip()
        
        ref_num_raw = request.form.get('reference_number', '')
        if isinstance(ref_num_raw, list):
            ref_num_raw = ref_num_raw[0]
        reference_number = (ref_num_raw or '').strip()

        if amount_paid > 0 or customer_deposit > 0:
            if payment_method.lower() == "cash":
                reference_number = None
            else:
                if not reference_number:
                    db.session.rollback()
                    flash("Reference number is required for non-cash payments.", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

                existing_payment = Payment.query.filter_by(
                    reference_number=reference_number
                ).first()

                if existing_payment:
                    db.session.rollback()
                    flash("Payment reference number already exists.", "danger")
                    return redirect(request.referrer or url_for('admin.transactions'))

        new_txn.payment_method = payment_method

        # 1. Add to generic Payment ledger (as a Deposit type)
        if customer_deposit > 0:
            db.session.add(Payment(
                transaction_id=new_txn.id,
                invoice_id=None,
                payment_type="Deposit",
                amount=customer_deposit,
                payment_method=payment_method,
                reference_number=reference_number,
                status="Completed",
                verified_by_id=current_user.id,
                verified_at=datetime.utcnow()
            ))

            # 2. ALSO explicitly populate the CustomerDeposit model table
            if new_txn.customer_id:
                db.session.add(CustomerDeposit(
                    customer_id=new_txn.customer_id,
                    transaction_id=new_txn.id,
                    amount=customer_deposit,
                    status="Held",
                    notes=f"Deposit collected via transaction {ref_no}"
                ))

        remaining_payment = amount_paid

        if remaining_payment > 0:
            if has_initial_fill and initial_fill_cost > 0:
                fill_pay_amount = min(remaining_payment, initial_fill_cost)
                if fill_pay_amount > 0:
                    db.session.add(Payment(
                        transaction_id=new_txn.id,
                        invoice_id=None,
                        payment_type="InitialFill",
                        amount=fill_pay_amount,
                        payment_method=payment_method,
                        reference_number=reference_number,
                        status="Completed",
                        verified_by_id=current_user.id,
                        verified_at=datetime.utcnow()
                    ))
                    remaining_payment -= fill_pay_amount

            for inv in all_invoices:
                if remaining_payment <= 0:
                    break
                pay_amount = min(remaining_payment, Decimal(str(inv.amount_due or 0)))
                if pay_amount > 0:
                    db.session.add(Payment(
                        transaction_id=new_txn.id,
                        invoice_id=inv.id,
                        payment_type="Rental",
                        amount=pay_amount,
                        payment_method=payment_method,
                        reference_number=reference_number,
                        status="Completed",
                        verified_by_id=current_user.id,
                        verified_at=datetime.utcnow()
                    ))
                    if pay_amount >= Decimal(str(inv.amount_due or 0)):
                        inv.status = "Paid"
                    else:
                        inv.status = "Partially Paid"
                    remaining_payment -= pay_amount

            if remaining_payment > 0:
                overpay_deposit = remaining_payment
                db.session.add(Payment(
                    transaction_id=new_txn.id,
                    invoice_id=None,
                    payment_type="Deposit",
                    amount=overpay_deposit,
                    payment_method=payment_method,
                    reference_number=reference_number,
                    status="Completed",
                    verified_by_id=current_user.id,
                    verified_at=datetime.utcnow()
                ))
                
                if new_txn.customer_id:
                    db.session.add(CustomerDeposit(
                        customer_id=new_txn.customer_id,
                        transaction_id=new_txn.id,
                        amount=overpay_deposit,
                        status="Held",
                        notes=f"Overpayment recorded as deposit via transaction {ref_no}"
                    ))

        db.session.flush()
        db.session.expire(new_txn, ['payments'])

        new_txn.update_totals() 
        db.session.commit()

        flash(f"Rental created successfully: {ref_no}", "success")
        return redirect(url_for("admin.transactions"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"RENTAL_ERROR: {str(e)}")
        flash("Rental processing failed.", "danger")
        return redirect(request.referrer or url_for('admin.transactions'))
    
@admin_bp.route('/product/<int:product_id>/history')
@login_required
@admin_or_staff_required
def product_history(product_id):
    try:
        logs = InventoryLog.query.filter_by(product_id=product_id)\
            .order_by(InventoryLog.created_at.desc(), InventoryLog.id.desc())\
            .limit(100)\
            .all()

        if not logs:
            product_exists = Product.query.get(product_id)
            if not product_exists:
                return jsonify({"status": "error", "message": "Product not found"}), 404
            return jsonify([]) 

        result = []
        for log in logs:
            movement_type = "neutral"
            if log.quantity and log.quantity > 0:
                movement_type = "increase"
            elif log.quantity and log.quantity < 0:
                movement_type = "decrease"

            result.append({
                "id": log.id,
                "action": log.action,
                "quantity": log.quantity if log.quantity != 0 else "-",
                "movement_type": movement_type, 
                "note": log.note or "No additional notes.",
                "user": log.user_name or "System",
                "reference": log.reference_no,
                "reason": log.reason_code,
                "balance_after": log.balance_after,
                "date": log.created_at.strftime("%b %d, %Y"),
                "time": log.created_at.strftime("%I:%M %p"),
                "timestamp": log.created_at.isoformat() 
            })

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error fetching history for Product {product_id}: {str(e)}")
        return jsonify({
            "status": "error", 
            "message": "Internal server error while fetching history."
        }), 500


@admin_bp.route('/transactions')
@login_required
@admin_or_staff_required
@csrf.exempt
@permission_required('can_process_transactions')
def transactions():
    current_date = datetime.now().date()

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search_query = request.args.get('q', '').strip()
    txn_type = request.args.get('type', '')
    fulfillment = request.args.get('fulfillment', '')
    status_filter = request.args.get('status', '')
 
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    query = Transaction.query.options(
        joinedload(Transaction.customer),
        selectinload(Transaction.rentals).options(
            selectinload(Rental.invoices),
            selectinload(Rental.product)
        ),
        selectinload(Transaction.payments)
    )

    if search_query:
        like = f"%{search_query}%"
        product_match = or_(
            Product.name.ilike(like),
            Product.equipment_type.ilike(like),
        )
        query = query.outerjoin(Rental, Rental.transaction_id == Transaction.id).filter(or_(
            Transaction.reference_no.ilike(like),
            Transaction.customer_name.ilike(like),
            Transaction.landmark.ilike(like),
            Rental.tanks.any(RentalTank.serial_number.ilike(like)),
            Transaction.purchases.any(Purchase.product.has(product_match)),
            Transaction.rentals.any(Rental.product.has(product_match)),
            Transaction.product.has(product_match),
        )).distinct()
    
    if txn_type:
        query = query.filter(Transaction.transaction_type == txn_type)
    
    if fulfillment:
        query = query.filter(Transaction.fulfillment_type == fulfillment)

    if start_date:
        try:
            parsed_start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Transaction.created_at >= parsed_start)
        except ValueError:
            pass

    if end_date:
        try:
            parsed_end = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.created_at <= parsed_end)
        except ValueError:
            pass
    
    # Status Filtering Logic
    if status_filter == 'expiring':
        from datetime import timedelta
        soon = current_date + timedelta(days=5)
        query = query.filter(
            Transaction.transaction_type == 'Rental',
            Transaction.rentals.any(
                and_(
                    Rental.status.in_(['Active', 'Partially Returned']),
                    Rental.expected_return_date >= current_date,
                    Rental.expected_return_date <= soon
                )
            )
        )
        
    elif status_filter == 'overdue_return':
        query = query.filter(
            Transaction.transaction_type == 'Rental',
            Transaction.rentals.any(
                and_(
                    Rental.status.in_(['Active', 'Partially Returned']),
                    Rental.expected_return_date < current_date
                )
            )
        )

    elif status_filter == 'overdue_payment':
        query = query.filter(
            Transaction.balance_due > 0,
            Transaction.rentals.any(
                Rental.invoices.any(
                    and_(
                        RentalInvoice.service_period_end < current_date,
                        RentalInvoice.status != 'Paid'
                    )
                )
            )
        )
 
    elif status_filter == 'unpaid':
        query = query.filter(
            Transaction.balance_due > 0,
            or_(Transaction.amount_paid == 0, Transaction.amount_paid.is_(None))
        )
 
    elif status_filter == 'partial':
        query = query.filter(
            Transaction.balance_due > 0,
            Transaction.amount_paid > 0
        )
 
    elif status_filter == 'submitted':
        query = query.filter(
            or_(
                Transaction.tracking_status == 'SUBMITTED',
                Transaction.status == 'submitted'
            )
        )

    if start_date:
        query = query.order_by(Transaction.created_at.asc())
    else:
        query = query.order_by(Transaction.created_at.desc())

    pagination = query.paginate(
        page=page, per_page=limit, error_out=False
    )

    for txn in pagination.items:
        rental_overdue = False
        if txn.rentals and txn.rentals[0].expected_return_date:
            ret_date = txn.rentals[0].expected_return_date
            if hasattr(ret_date, 'date'):
                ret_date = ret_date.date()
            rental_overdue = ret_date < current_date
            
        txn.calculated_overdue = txn.balance_due > 0 and (getattr(txn, 'is_overdue', False) or rental_overdue)

    stats = {
        'pending': Transaction.query.filter_by(payment_status='Unpaid').count(),
        'alerts': Transaction.query.filter(Transaction.status == 'Due').count(),
        'empty_tanks': Product.query.filter(Product.status.ilike('%Empty%')).count()
    }
    
    customers = Customer.query.order_by(Customer.last_name).all()
    all_equipment = Product.query.filter_by(status='Available').order_by(Product.equipment_type.asc()).all()
    
    for equipment in all_equipment:
        if equipment.is_refillable and equipment.tank_status:
            equipment.available_stock = equipment.tank_status.full_in_stock or 0
        else:
            equipment.available_stock = equipment.stock or 0

    raw_refillables = Product.query.options(
        joinedload(Product.tank_status)
    ).join(TankStatus).filter(Product.is_active == True).all()
    
    grouped_refills = {}
    for p in raw_refillables:
        key = (p.name, p.size)
        if key not in grouped_refills:
            grouped_refills[key] = p
    
    unique_refillable_products = list(grouped_refills.values())

    raw_active_rentals = Rental.query.join(Product).filter(
        Rental.status == 'Active',
        Product.name.ilike('%Oxygen%')
    ).all()

    active_rentals_list = []
    for rental in raw_active_rentals:
        for tank in rental.tanks:
            if tank.status == "Active" and tank.serial_number:
                clean_sn = tank.serial_number.strip()
                if clean_sn:
                    active_rentals_list.append({
                        'customer_id': rental.customer_id,
                        'serial_number': clean_sn,
                        'product_name': rental.product.name if rental.product else 'Oxygen Tank',
                        'product_size': rental.product.size if rental.product and rental.product.size else 'Standard'
                    })
    
    return render_template(
        "admin/transactions.html",
        transactions=pagination.items,
        pagination=pagination,
        search_query=search_query,
        current_limit=limit,
        current_type=txn_type,
        current_fulfillment=fulfillment,
        current_status=status_filter,
        start_date=start_date,      
        end_date=end_date,          
        customers=customers,
        all_equipment=all_equipment,
        refillable_products=unique_refillable_products,
        active_rentals_list=active_rentals_list,
        datetime_now_date=current_date,
        **stats
    )

def _apply_transaction_cancellation(txn, reason, actor=None):
    """Reverse stock effects for a void. Used by admins and by approval of a
    staff request (Table 15: reference number, reason, admin approval)."""
    txn.status = 'Cancelled'
    txn.tracking_status = 'CANCELLED'
    if hasattr(txn, 'cancellation_reason'):
        txn.cancellation_reason = reason

    actor_id = getattr(actor, 'id', None)
    actor_name = getattr(actor, 'full_name', 'System Administrator')

    if txn.transaction_type == 'Sale' and txn.purchases:
        for purchase in txn.purchases:
            product = purchase.product
            if product and purchase.quantity:
                product.stock = (product.stock or 0) + purchase.quantity
                db.session.add(InventoryLog(
                    product_id=product.id,
                    transaction_id=txn.id,
                    reference_no=txn.reference_no,
                    reason_code='VOID_SALE',
                    action='Transaction Cancelled Restock',
                    quantity=purchase.quantity,
                    balance_after=product.stock,
                    note=f'Restocked from cancelled txn {txn.reference_no}. Reason: {reason}',
                    user_id=actor_id,
                    user_name=actor_name,
                ))

    elif txn.transaction_type == 'Rental' and txn.rentals:
        for rental in txn.rentals:
            rental.status = 'Cancelled'
            for invoice in rental.invoices:
                if invoice.status != 'Paid':
                    invoice.status = 'Cancelled'

            if rental.product:
                remaining = rental.remaining_to_return or 0
                balance_after = rental.product.stock
                if rental.product.tank_status:
                    tank_info = rental.product.tank_status
                    tank_info.rented_out = max(
                        0, (tank_info.rented_out or 0) - remaining
                    )
                    tank_info.full_in_stock = (
                        tank_info.full_in_stock or 0
                    ) + remaining
                    balance_after = tank_info.full_in_stock
                    db.session.add(tank_info)
                else:
                    rental.product.stock = (
                        rental.product.stock or 0
                    ) + remaining
                    balance_after = rental.product.stock
                    if rental.product.stock > 0:
                        rental.product.status = 'Available'

                db.session.add(InventoryLog(
                    product_id=rental.product.id,
                    transaction_id=txn.id,
                    reference_no=txn.reference_no,
                    reason_code='VOID_RENTAL',
                    action='Rental Transaction Cancelled Restock',
                    quantity=remaining,
                    balance_after=balance_after,
                    note=f'Restocked from cancelled rental txn {txn.reference_no}. Reason: {reason}',
                    user_id=actor_id,
                    user_name=actor_name,
                ))

    elif txn.transaction_type == 'Refill' and txn.product_id:
        product = Product.query.get(txn.product_id)
        if product and txn.quantity:
            product.stock = (product.stock or 0) + txn.quantity
            db.session.add(InventoryLog(
                product_id=product.id,
                transaction_id=txn.id,
                reference_no=txn.reference_no,
                reason_code='VOID_REFILL',
                action='Refill Transaction Cancelled Restock',
                quantity=txn.quantity,
                balance_after=product.stock,
                note=f'Restocked from cancelled refill txn {txn.reference_no}. Reason: {reason}',
                user_id=actor_id,
                user_name=actor_name,
            ))

    txn.amount_paid = Decimal('0.00')
    txn.balance_due = Decimal('0.00')
    if hasattr(txn, 'payment_status'):
        txn.payment_status = 'Cancelled'


@admin_bp.route('/transactions/cancel/<int:txn_id>', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_process_transactions')
def cancel_transaction(txn_id):
    try:
        txn = Transaction.query.get_or_404(txn_id)
        
        if txn.status == 'Cancelled':
            return jsonify({'success': False, 'message': 'This transaction is already cancelled.'}), 400

        data = request.get_json() or {}
        reason = data.get('reason', '').strip()
        
        if not reason:
            return jsonify({'success': False, 'message': 'A cancellation reason is required.'}), 400

        # Table 15: staff requests must be approved by an Administrator.
        if (current_user.role or '').strip() != 'Administrator':
            existing = VoidRequest.query.filter_by(
                transaction_id=txn.id, status='Pending'
            ).first()
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'A void request for this transaction is already awaiting approval.'
                }), 400
            db.session.add(VoidRequest(
                transaction_id=txn.id,
                reason=reason,
                requested_by_id=current_user.id,
                status='Pending',
            ))
            db.session.commit()
            return jsonify({
                'success': True,
                'pending': True,
                'message': 'Void request submitted. An Administrator must approve it before stock is restored.'
            }), 202

        _apply_transaction_cancellation(txn, reason, current_user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Transaction has been successfully cancelled, payment amounts cleared, and inventory levels have been restored.'
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"CANCEL_TRANSACTION_ERROR | ID: {txn_id} | Error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'An error occurred while cancelling the transaction: {str(e)}'
        }), 500
        
@admin_bp.route('/active-rentals')
@login_required
@admin_or_staff_required
@permission_required('can_view_active_rentals')
def active_rentals():
    from datetime import date

    search_query = request.args.get('q', '').strip()
    filter_type = request.args.get('filter', '')  
   
    active_statuses = ['Active', 'Overdue', 'Awaiting Return', 'Partially Returned']
    
    query = Rental.query.filter(Rental.status.in_(active_statuses))\
        .options(
            joinedload(Rental.product),
            joinedload(Rental.transaction).joinedload(Transaction.customer)
        )

    today = date.today()
    if filter_type == 'overdue_return':
        query = query.filter(Rental.expected_return_date < today)
    elif filter_type == 'awaiting_return':
        query = query.filter(Rental.status == 'Awaiting Return')
    elif filter_type == 'partial_return':
        query = query.filter(Rental.status == 'Partially Returned')
    
    rentals = query.order_by(Rental.expected_return_date.asc()).all()
    
    return render_template(
        'admin/active_rentals.html',
        rentals=rentals,
        search_query=search_query,
        datetime_now_date=date.today(),
        current_filter=filter_type 
    )
    
@admin_bp.route('/collection-monitoring')
@login_required
def collection_monitoring():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search_query = request.args.get('q', '', type=str)

    today = datetime.now().date()
    three_days_later = today + timedelta(days=3)

    query = RentalInvoice.query.join(RentalInvoice.rental).filter(
        and_(
            or_(
                RentalInvoice.service_period_start <= three_days_later,
                Rental.expected_return_date <= three_days_later
            ),
            RentalInvoice.status.notin_(['Cancelled', 'Paid'])
        )
    )
    
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            RentalInvoice.invoice_number.ilike(search_term)
        )

    pagination = query.paginate(page=page, per_page=limit, error_out=False)
    due_invoices = pagination.items

    return render_template(
        'admin/collection_monitoring.html',
        due_invoices=due_invoices,
        pagination=pagination,
        current_limit=limit,
        search_query=search_query,
        now=datetime.now()
    )
    
    
@admin_bp.route('/invoice/<int:id>/pay', methods=['GET', 'POST'])
@login_required
def process_payment(id):

    return render_template('admin/process_payment.html')

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from io import BytesIO
from flask import make_response

@admin_bp.route('/transactions/export')
@login_required
@admin_or_staff_required
@permission_required('can_process_transactions')
def export_transactions():
    search_query = request.args.get('q', '').strip()
    txn_type = request.args.get('type', '')
    fulfillment = request.args.get('fulfillment', '')
    status_filter = request.args.get('status', '')
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    query = Transaction.query.options(
        joinedload(Transaction.customer),
        selectinload(Transaction.rentals)
    )

    if start_date_str:
        try:
            query = query.filter(
                Transaction.created_at >= datetime.strptime(start_date_str, '%Y-%m-%d')
            )
        except ValueError:
            flash("Invalid start date for export; ignored.", "warning")
    if end_date_str:
        try:
            exclusive_end = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Transaction.created_at < exclusive_end)
        except ValueError:
            flash("Invalid end date for export; ignored.", "warning")

    if search_query:
        like = f"%{search_query}%"
        product_match = or_(
            Product.name.ilike(like),
            Product.equipment_type.ilike(like),
        )
        query = query.filter(or_(
            Transaction.reference_no.ilike(like),
            Transaction.customer_name.ilike(like),
            Transaction.landmark.ilike(like),
            Transaction.purchases.any(Purchase.product.has(product_match)),
            Transaction.rentals.any(Rental.product.has(product_match)),
            Transaction.product.has(product_match),
        ))
    if txn_type:
        query = query.filter(Transaction.transaction_type == txn_type)
    if fulfillment:
        query = query.filter(Transaction.fulfillment_type == fulfillment)
    if status_filter == 'overdue':
        current_date = datetime.now().date()
        query = query.filter(
            Transaction.balance_due > 0,
            or_(
                Transaction.status == 'Due', 
                Transaction.rentals.any(Rental.expected_return_date < current_date)
            )
        )

    transactions_list = query.order_by(Transaction.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"

    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="16A34A", end_color="16A34A", fill_type="solid") # Matching dashboard green
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    headers = [
        'Reference No', 'Customer Name', 'Type', 'Fulfillment', 'Total Amount',
        'Amount Paid', 'Balance Due', 'Deposit Held', 'Distance (km)',
        'Deposit Rule', 'Status', 'Date',
    ]
    ws.append(headers)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    for txn in transactions_list:
        cust_name = txn.customer_name or (f"{txn.customer.first_name} {txn.customer.last_name}" if txn.customer else "—")
        txn_date = txn.created_at.strftime('%Y-%m-%d') if txn.created_at else "—"
        
        row_data = [
            txn.reference_no,
            cust_name,
            txn.transaction_type,
            txn.fulfillment_type,
            txn.total_amount,
            txn.amount_paid,
            txn.balance_due,
            txn.deposit_amount,
            txn.distance_km,
            txn.deposit_rule,
            txn.status,
            txn_date
        ]
        ws.append(row_data)
        
        current_row = ws.max_row
        for money_col in (5, 6, 7, 8):
            cell = ws.cell(row=current_row, column=money_col)
            cell.number_format = '"₱"#,##0.00'
            cell.alignment = right_align
        ws.cell(row=current_row, column=9).alignment = right_align
        for center_col in (4, 11, 12):
            ws.cell(row=current_row, column=center_col).alignment = center_align

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Save to memory buffer
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # Send response file download stream
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=transactions_export.xlsx"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

@admin_bp.route('/transaction_details/<int:id>') 
@login_required
def transaction_details(id):
    txn = Transaction.query.get_or_404(id)

    if txn.transaction_type == 'Rental':
        today = datetime.now().date()
        invoices_generated_flag = False
        
        for rental in txn.rentals:
            if rental.status == 'Active' and rental.is_open_duration:
                latest_invoice = rental.get_latest_invoice()
                if latest_invoice:
                    days_remaining = (latest_invoice.service_period_end - today).days
                    if days_remaining <= 3:
                        rental.generate_next_monthly_invoice()
                        invoices_generated_flag = True
                        
        if invoices_generated_flag:
            db.session.commit()

    txn.update_totals()
    db.session.commit()
    
    return render_template('admin/transaction_details.html', txn=txn, current_date=datetime.now().date())

@admin_bp.route('/api/cron/generate-invoices', methods=['POST', 'GET'])
def cron_generate_invoices():

    auth_token = request.headers.get('X-Cron-Token') or request.args.get('token')
    expected_token = current_app.config.get('CRON_SECRET_KEY', 'your-fallback-secret-key')
    
    if auth_token != expected_token:
        abort(403)
        
    try:
        open_rentals = Rental.query.filter_by(status='Active', is_open_duration=True).all()
        generated_count = 0
        today = datetime.now().date()
        
        for rental in open_rentals:
            latest_invoice = rental.get_latest_invoice()
            if latest_invoice:
                days_remaining = (latest_invoice.service_period_end - today).days
                if days_remaining <= 3:
                    rental.generate_next_monthly_invoice()
                    generated_count += 1
                    
        db.session.commit()
        return jsonify({"status": "success", "invoices_generated": generated_count}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@admin_bp.route('/transaction/<int:txn_id>/update-tracking', methods=['POST'])
@login_required
def update_tracking(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    new_status = request.form.get('tracking_status')

    valid_statuses = ['SUBMITTED', 'VERIFIED', 'SHIPPED', 'DELIVERED', 'CANCELLED']

    if new_status in valid_statuses:
        if txn.tracking_status == 'CANCELLED':
            flash("Action denied: This transaction has already been canceled.", "warning")
            return redirect(url_for('admin.transaction_details', id=txn.id))

        txn.tracking_status = new_status

        if new_status == 'CANCELLED':
            txn.status = 'Cancelled' 
        elif new_status == 'DELIVERED':
            txn.delivery_status = 'Delivered'
            if txn.transaction_type != 'Rental':
                txn.status = 'Closed'

        try:
            txn.update_totals()
            db.session.commit()
            flash(f"Success: Status updated to '{new_status.title()}'.", "success")
        except Exception as e:
            db.session.rollback()
            flash("System Error: Could not update status.", "danger")
    else:
        flash("Update Failed: Invalid status provided.", "danger")

    return redirect(url_for('admin.transaction_details', id=txn.id))

@admin_bp.route('/post-payment', methods=['POST'])
@login_required
@admin_or_staff_required
def post_payment():
    txn_id = request.form.get('txn_id')
    invoice_id = request.form.get('invoice_id')  
    payment_type = request.form.get('payment_type', 'Rental')

    try:
        raw_amount = request.form.get('amount', '0').replace(',', '').strip()
        amount = Decimal(raw_amount)

        if amount <= 0:
            flash('Payment amount must be greater than zero.', 'warning')
            return redirect(request.referrer or url_for('admin.transactions'))

        txn = Transaction.query.with_for_update().get_or_404(txn_id)

        allowed_methods = ["Cash", "GCash", "Bank Transfer", "Check"]
        method = request.form.get('method')

        if method not in allowed_methods:
            flash("Invalid payment method.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        ref_number = request.form.get('payment_reference', '').strip() or None

        if method in ["GCash", "Bank Transfer", "Check"] and not ref_number:
            flash("Reference number is required for this payment method.", "warning")
            return redirect(request.referrer or url_for('admin.transactions'))

        if ref_number and Payment.query.filter_by(reference_number=ref_number).first():
            flash("Reference number already exists.", "danger")
            return redirect(request.referrer or url_for('admin.transactions'))

        receipt_path = None
        file = request.files.get('receipt_image')
        if file and file.filename:
            filename = secure_filename(f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'receipts')
            os.makedirs(upload_folder, exist_ok=True)
            file.save(os.path.join(upload_folder, filename))
            receipt_path = f'uploads/receipts/{filename}'

        if txn.transaction_type == 'Sale' or txn.transaction_type == 'Purchase':
            sale_balance = Decimal(str(txn.balance_due or 0))
            if sale_balance <= 0:
                flash('This transaction is already fully paid.', 'info')
                return redirect(request.referrer or url_for('admin.transactions'))
            if amount > sale_balance:
                flash(f'Payment ₱{amount:,.2f} exceeds the remaining balance of ₱{sale_balance:,.2f}.', 'danger')
                return redirect(request.referrer or url_for('admin.transactions'))

            payment = Payment(
                transaction_id=txn.id, 
                payment_type="Sale",
                amount=amount, 
                payment_method=method, 
                reference_number=ref_number, 
                receipt_image_path=receipt_path,
                status="Completed", 
                verified_by_id=current_user.id, 
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)

        elif payment_type == 'InitialFill':
            initial_fill_balance = txn.initial_fill_balance

            if initial_fill_balance <= 0:
                flash('Initial fill fee is already fully paid.', 'info')
                return redirect(request.referrer or url_for('admin.transactions'))

            if amount > initial_fill_balance:
                flash(f'Payment ₱{amount:,.2f} exceeds the initial fill balance of ₱{initial_fill_balance:,.2f}.', 'danger')
                return redirect(request.referrer or url_for('admin.transactions'))

            payment = Payment(
                transaction_id=txn.id,
                invoice_id=None, 
                payment_type="InitialFill",
                amount=amount,
                payment_method=method,
                reference_number=ref_number,
                receipt_image_path=receipt_path,
                status="Completed",
                verified_by_id=current_user.id,
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)

        else:
            if not invoice_id:
                flash("Please select a specific item/invoice to pay.", "warning")
                return redirect(request.referrer or url_for('admin.transactions'))

            rental_ids = [r.id for r in txn.rentals]
            target_invoice = RentalInvoice.query.filter(
                RentalInvoice.id == invoice_id,
                RentalInvoice.rental_id.in_(rental_ids)
            ).first()

            if not target_invoice:
                flash("Invalid invoice selected.", "danger")
                return redirect(request.referrer or url_for('admin.transactions'))

            if amount > target_invoice.remaining_balance:
                flash(f'Payment ₱{amount:,.2f} exceeds the invoice balance of ₱{target_invoice.remaining_balance:,.2f}.', 'danger')
                return redirect(request.referrer or url_for('admin.transactions'))

            payment = Payment(
                transaction_id=txn.id, 
                invoice_id=target_invoice.id, 
                payment_type="Rental",
                amount=amount,
                payment_method=method, 
                reference_number=ref_number, 
                receipt_image_path=receipt_path, 
                status="Completed",
                verified_by_id=current_user.id, 
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)

            if amount >= target_invoice.remaining_balance:
                target_invoice.status = "Paid"
            else:
                target_invoice.status = "Partially Paid"

        db.session.expire(txn, ['payments'])
        txn.update_totals()

        if txn.balance_due <= 0 and txn.status not in ['Closed', 'Cancelled']:
            if txn.transaction_type == 'Rental':
                all_returned = all(getattr(r, 'remaining_to_return', 0) == 0 for r in txn.rentals)
                if all_returned:
                    txn.status = 'Closed'
            else:
                txn.status = 'Closed'

        db.session.commit()

        flash(f'Payment of ₱{amount:,.2f} recorded successfully.', 'success')

    except (InvalidOperation, ValueError):
        db.session.rollback()
        flash('Invalid amount format.', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PAYMENT_ERROR | TXN: {txn_id} | Error: {str(e)}")
        flash(f'A system error occurred: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('admin.transactions'))

@admin_bp.route('/invoice/cancel/<int:invoice_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def cancel_invoice(invoice_id):
    try:
        invoice = RentalInvoice.query.get_or_404(invoice_id)
        
        if invoice.status == 'Cancelled':
            flash('This invoice is already cancelled.', 'warning')
            return redirect(request.referrer or url_for('admin.transactions'))

        if invoice.remaining_balance <= 0:
            flash('Cannot cancel an invoice that has already been fully paid or settled.', 'danger')
            return redirect(request.referrer or url_for('admin.transactions'))
            
        invoice.status = 'Cancelled'

        txn = None
        if invoice.rental and invoice.rental.transaction:
            txn = invoice.rental.transaction
            db.session.expire(txn, ['payments'])
            txn.update_totals()

            if txn.balance_due <= 0 and txn.status not in ['Closed', 'Cancelled']:
                if txn.transaction_type == 'Rental':
                    all_returned = all(getattr(r, 'remaining_to_return', 0) == 0 for r in txn.rentals)
                    if all_returned:
                        txn.status = 'Closed'
                else:
                    txn.status = 'Closed'

        db.session.commit()
        flash('Invoice has been successfully cancelled.', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"CANCEL_INVOICE_ERROR | ID: {invoice_id} | Error: {str(e)}")
        flash(f'An error occurred while cancelling the invoice: {str(e)}', 'danger')
        
    return redirect(request.referrer or url_for('admin.transactions'))

@admin_bp.route('/confirm-payment-proof/<int:proof_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def confirm_payment_proof(proof_id):
    proof = PaymentProof.query.get_or_404(proof_id)
    txn = Transaction.query.get_or_404(proof.transaction_id)

    try:
        # Guard: don't double-record the same reference number
        existing_payment = Payment.query.filter_by(
            reference_number=proof.reference_number
        ).first()

        if existing_payment:
            # Already recorded — just mark the proof as verified
            proof.status = 'Verified'
            proof.payment_id = existing_payment.id
            db.session.flush()
            db.session.expire(txn, ['payments'])
            txn.update_totals()
            db.session.commit()
            flash('Payment proof verified successfully.', 'success')
            return redirect(url_for('admin.transaction_details', id=txn.id))

        # No existing payment — create one for the remaining balance
        remaining = Decimal(str(txn.balance_due or 0))

        if remaining <= 0:
            flash('This transaction is already fully paid.', 'info')
            return redirect(url_for('admin.transaction_details', id=txn.id))

        # For rentals: attach to the oldest unpaid invoice
        invoice_id_to_use = None
        if txn.transaction_type == 'Rental':
            unpaid_invoice = RentalInvoice.query.filter(
                RentalInvoice.rental_id.in_([r.id for r in txn.rentals]),
                RentalInvoice.status != 'Paid'
            ).order_by(RentalInvoice.service_period_start.asc()).first()

            if unpaid_invoice:
                invoice_id_to_use = unpaid_invoice.id
                pay_amount = min(remaining, unpaid_invoice.remaining_balance)

                if pay_amount >= unpaid_invoice.remaining_balance:
                    unpaid_invoice.status = 'Paid'
                else:
                    unpaid_invoice.status = 'Partially Paid'
            else:
                pay_amount = remaining
        else:
            pay_amount = remaining

        new_payment = Payment(
            transaction_id=txn.id,
            invoice_id=invoice_id_to_use,
            amount=pay_amount,
            payment_method='GCash',
            reference_number=proof.reference_number,
            status='Completed',
            verified_by_id=current_user.id,
            verified_at=datetime.utcnow()
        )
        db.session.add(new_payment)
        db.session.flush()

        proof.status = 'Verified'
        proof.payment_id = new_payment.id

        # ── Let update_totals() handle all status strings ──
        db.session.expire(txn, ['payments'])
        txn.update_totals()
        db.session.commit()

        flash('Payment confirmed and marked as Paid successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PROOF_CONFIRM_ERROR | proof {proof_id} | {str(e)}")
        flash(f'Failed to confirm payment: {str(e)}', 'error')

    return redirect(url_for('admin.transaction_details', id=txn.id))


@admin_bp.route('/transaction/<int:txn_id>/return', methods=['POST'])
@login_required
@admin_or_staff_required
def process_return(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    returned_item_ids = request.form.getlist('returned_items')
    return_notes = request.form.get('return_notes', '').strip()
    raw_late_fees = request.form.get('late_fees', '0')
    payment_method = request.form.get('payment_method', 'Cash')
  
    refund_deposit = request.form.get('refund_deposit') == 'yes'
    raw_deposit_refund = request.form.get('deposit_refund_amount', '0')

    if not returned_item_ids and not refund_deposit:
        flash("No items or deposit refund actions were selected.", "warning")
        return redirect(url_for('admin.transaction_details', id=txn.id))

    try:
        late_fees = Decimal(str(raw_late_fees))
    except (InvalidOperation, ValueError, TypeError):
        late_fees = Decimal('0.00')

    try:
        deposit_refund_amount = Decimal(str(raw_deposit_refund))
    except (InvalidOperation, ValueError, TypeError):
        deposit_refund_amount = Decimal('0.00')

    # RULE-10 / TC-11: a damaged return needs a reason code and an
    # Administrator's approval. Validate before mutating any rental/stock row.
    damage_items = []
    damage_reasons = {}
    for item_id in returned_item_ids:
        if not str(item_id).isdigit():
            continue
        rental = db.session.get(Rental, int(item_id))
        if not rental or rental.transaction_id != txn.id:
            continue

        qty_input = request.form.get(f'qty_{item_id}', '0')
        qty_to_return = int(qty_input) if qty_input.isdigit() else 0
        qty_to_return = min(qty_to_return, rental.remaining_to_return)
        if qty_to_return <= 0:
            continue

        condition = (request.form.get(f'condition_{item_id}') or 'Good').strip()
        if condition not in ('Good',) + DAMAGE_CONDITIONS:
            condition = 'Good'
        if condition not in DAMAGE_CONDITIONS:
            continue

        reason = (request.form.get(f'damage_reason_{item_id}') or '').strip()
        damage_items.append((rental, condition, str(item_id)))
        if reason:
            damage_reasons[str(item_id)] = reason

    if damage_items and (current_user.role or '').strip() != 'Administrator':
        flash(
            "Damaged returns require Administrator approval. "
            "Please ask an Administrator to process this return.",
            "danger",
        )
        return redirect(url_for('admin.transaction_details', id=txn.id))

    for rental, condition, item_id in damage_items:
        reason = damage_reasons.get(item_id)
        if reason not in DAMAGE_REASON_CODES:
            flash(
                f"Select a valid damage reason for {rental.product.name} "
                f"({condition}).",
                "danger",
            )
            return redirect(url_for('admin.transaction_details', id=txn.id))
        if reason == 'Other' and not return_notes:
            flash(
                f"Describe the damage for {rental.product.name} in Return Notes "
                "when the reason is 'Other'.",
                "danger",
            )
            return redirect(url_for('admin.transaction_details', id=txn.id))

    try:
        user_display_name = f"{current_user.first_name} {current_user.last_name}"
        items_processed = 0
        computed_late_fees = Decimal('0.00')
        late_rate = Decimal(str(SystemSetting.value_of('late_fee_per_day') or '0'))
        deposit_held = Decimal(str(txn.deposit_amount or 0))
        minor_pct = Decimal(str(SystemSetting.value_of('damage_fee_minor_pct') or 0))
        major_pct = Decimal(str(SystemSetting.value_of('damage_fee_major_pct') or 0))
        percent_damage_total = Decimal('0.00')
        damage_fee_total = Decimal('0.00')
        today = datetime.utcnow().date()

        for item_id in returned_item_ids:
            rental = Rental.query.get(int(item_id))
            if not rental or rental.transaction_id != txn.id:
                continue

            qty_input = request.form.get(f'qty_{item_id}', '0')
            qty_to_return = int(qty_input) if qty_input.isdigit() else 0
            
            if qty_to_return > rental.remaining_to_return:
                qty_to_return = rental.remaining_to_return
            
            if qty_to_return > 0:
                # RULE-09: days overdue x daily rate x units actually returned.
                days_late = 0
                if rental.expected_return_date and today > rental.expected_return_date:
                    days_late = (today - rental.expected_return_date).days
                item_late_fee = (late_rate * days_late * qty_to_return).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                if item_late_fee > 0:
                    computed_late_fees += item_late_fee
                    rental.late_fees_incurred = (
                        Decimal(str(rental.late_fees_incurred or 0)) + item_late_fee
                    )

                rental.quantity_returned = (rental.quantity_returned or 0) + qty_to_return
                if rental.quantity_returned >= rental.quantity:
                    rental.status = 'Returned'
                    rental.actual_return_date = datetime.utcnow().date()
                else:
                    rental.status = 'Partially Returned'
                
                return_status = request.form.get(f'status_{item_id}', 'Full')
                condition = (request.form.get(f'condition_{item_id}') or 'Good').strip()
                if condition not in ('Good',) + DAMAGE_CONDITIONS:
                    condition = 'Good'
                damage_reason = (
                    damage_reasons.get(str(item_id))
                    if condition in DAMAGE_CONDITIONS
                    else None
                )

                # RULE-10: assess the damage fee against the held deposit.
                item_damage_fee = Decimal('0.00')
                if condition == 'Minor Damage':
                    item_damage_fee = (
                        deposit_held * minor_pct / Decimal('100') * qty_to_return
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    percent_damage_total += item_damage_fee
                elif condition == 'Major Damage':
                    item_damage_fee = (
                        deposit_held * major_pct / Decimal('100') * qty_to_return
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    percent_damage_total += item_damage_fee
                elif condition == 'Total Loss':
                    cash_value = Decimal(str(rental.product.sale_price or 0))
                    if cash_value <= 0:
                        cash_value = Decimal(str(rental.product.cost_price or 0))
                    if cash_value <= 0:
                        cash_value = deposit_held
                    item_damage_fee = (cash_value * qty_to_return).quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
                    damage_fee_total += item_damage_fee

                rental.return_condition = condition
                rental.damage_fee = (rental.damage_fee or 0) + item_damage_fee
                if condition in DAMAGE_CONDITIONS:
                    rental.damage_reason = damage_reason
                    rental.damage_approved_by_id = current_user.id
                    rental.damage_approved_at = datetime.utcnow()
                    rental.return_condition_notes = (
                        return_notes or rental.return_condition_notes
                    )
                log_balance = rental.product.stock or 0

                if condition == 'Total Loss':
                    # The asset is gone: remove it from the tank registry without
                    # returning it to sellable stock.
                    if rental.product.tank_status:
                        tank_info = rental.product.tank_status
                        tank_info.rented_out = max(
                            0, (tank_info.rented_out or 0) - qty_to_return
                        )
                        tank_info.total_owned = max(
                            0, (tank_info.total_owned or 0) - qty_to_return
                        )
                        rental.product.stock = max(
                            0, (rental.product.stock or 0) - qty_to_return
                        )
                        log_balance = tank_info.full_in_stock or 0
                        db.session.add(tank_info)
                    db.session.add(rental.product)
                    log_reason = "RETURN_TOTAL_LOSS"
                    log_qty = 0

                elif condition in ('Minor Damage', 'Major Damage'):
                    # Returned but not rentable until repaired.
                    if rental.product.tank_status:
                        tank_info = rental.product.tank_status
                        tank_info.rented_out = max(
                            0, (tank_info.rented_out or 0) - qty_to_return
                        )
                        tank_info.damaged_in_stock = (
                            tank_info.damaged_in_stock or 0
                        ) + qty_to_return
                        log_balance = tank_info.damaged_in_stock
                        db.session.add(tank_info)
                    else:
                        rental.product.damaged_stock = (
                            rental.product.damaged_stock or 0
                        ) + qty_to_return
                        log_balance = rental.product.damaged_stock
                    db.session.add(rental.product)
                    log_reason = "RETURN_DAMAGED"
                    log_qty = 0

                elif rental.product.tank_status:
                    tank_info = rental.product.tank_status

                    tank_info.rented_out = max(0, (tank_info.rented_out or 0) - qty_to_return)

                    if return_status == 'Empty':
                        tank_info.empty_in_stock = (tank_info.empty_in_stock or 0) + qty_to_return
                        log_balance = tank_info.empty_in_stock
                    else:
                        tank_info.full_in_stock = (tank_info.full_in_stock or 0) + qty_to_return
                        log_balance = tank_info.full_in_stock
                    
                    if rental.product.stock > 0:
                        rental.product.status = "Available"
                        
                    db.session.add(tank_info)
                    db.session.add(rental.product)
                    log_reason = "RETURN"
                    log_qty = qty_to_return

                else:
                    rental.product.stock = (rental.product.stock or 0) + qty_to_return
                    log_balance = rental.product.stock
                    if rental.product.stock > 0:
                        rental.product.status = "Available"
                    db.session.add(rental.product)
                    log_reason = "RETURN"
                    log_qty = qty_to_return

                db.session.add(InventoryLog(
                    product_id=rental.product.id,
                    transaction_id=txn.id,
                    reference_no=txn.reference_no,
                    reason_code=log_reason,
                    action="Equipment Return",
                    quantity=log_qty,
                    balance_after=log_balance,
                    note=(
                        f"Txn {txn.reference_no} Return. Condition: "
                        f"{condition}{f' ({damage_reason})' if damage_reason else ''}. "
                        f"Tank status: {return_status}. {return_notes}"
                    ),
                    user_id=current_user.id,
                    user_name=user_display_name
                ))
                if condition in DAMAGE_CONDITIONS:
                    db.session.add(SecurityLog(
                        event_type="Damage Approved",
                        description=(
                            f"Txn {txn.reference_no} | {rental.product.name} | "
                            f"{condition} | Reason: {damage_reason} | "
                            f"Fee: ₱{item_damage_fee:,.2f} | "
                            f"Approved by Administrator {current_user.email}."
                        ),
                        user_id=current_user.id,
                        user_email=current_user.email,
                        severity="High" if condition == 'Total Loss' else "Medium",
                    ))
                items_processed += 1

        # Percentage-based damage is capped at the deposit actually held.
        damage_fee_total += min(percent_damage_total, deposit_held)
        damage_fee_total = damage_fee_total.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        # The computed amount is authoritative unless an Administrator overrides
        # it with a positive value. A blank/zero field means "use the computed fee".
        if late_fees <= 0:
            late_fees = computed_late_fees
        elif late_fees != computed_late_fees:
            if (current_user.role or '').strip() == 'Administrator':
                db.session.add(SecurityLog(
                    event_type="Late Fee Override",
                    description=(
                        f"Txn {txn.reference_no}: late fee changed from "
                        f"₱{computed_late_fees:,.2f} (computed) to ₱{late_fees:,.2f}."
                    ),
                    user_id=current_user.id,
                    user_email=current_user.email,
                    severity="Medium",
                ))
            else:
                flash(
                    f"Late fee was auto-computed as ₱{computed_late_fees:,.2f} "
                    f"(₱{late_rate:,.2f}/day per unit). Only an Administrator can override it.",
                    "info",
                )
                late_fees = computed_late_fees

        if late_fees > 0:
            # RULE-09: every assessed late fee is written to the audit log,
            # including the auto-computed amount and the configured daily rate.
            db.session.add(SecurityLog(
                event_type="Late Fee Assessed",
                description=(
                    f"Txn {txn.reference_no}: late fee ₱{late_fees:,.2f} "
                    f"(computed ₱{computed_late_fees:,.2f}; "
                    f"rate ₱{late_rate:,.2f}/day/unit)."
                ),
                user_id=current_user.id,
                user_email=current_user.email,
                severity="Low",
            ))
            payment = Payment(
                transaction_id=txn.id,
                amount=late_fees,
                payment_method=payment_method,
                payment_type="Late Fee",
                status="Completed",
            )
            db.session.add(payment)

        net_deposit_refund = Decimal('0.00')
        if refund_deposit and deposit_refund_amount > 0:
            net_deposit_refund = max(
                Decimal('0.00'), deposit_refund_amount - damage_fee_total
            )
            held_deposits = CustomerDeposit.query.filter_by(transaction_id=txn.id, status='Held').all()
            for deposit in held_deposits:
                deposit_amount = Decimal(str(deposit.amount or 0))
                if deposit_amount > 0 and damage_fee_total >= deposit_amount:
                    deposit.status = 'Forfeited'
                elif net_deposit_refund >= deposit_amount and deposit_amount > 0:
                    deposit.status = 'Refunded'
                elif net_deposit_refund > 0:
                    deposit.status = 'Partially Refunded'
                else:
                    deposit.status = 'Forfeited'
                if damage_fee_total > 0:
                    deposit.notes = (
                        f"{deposit.notes or ''} Damage fee ₱{damage_fee_total:,.2f} "
                        f"deducted on return.".strip()
                    )
                db.session.add(deposit)

            if net_deposit_refund > 0:
                deposit_payout = Payment(
                    transaction_id=txn.id,
                    amount=net_deposit_refund,
                    payment_method=payment_method,
                    payment_type="Deposit Refund",
                    status="Completed",
                )
                db.session.add(deposit_payout)

        elif damage_fee_total > 0:
            # A total loss can consume the entire deposit without a refund action.
            held_deposits = CustomerDeposit.query.filter_by(transaction_id=txn.id, status='Held').all()
            for deposit in held_deposits:
                deposit_amount = Decimal(str(deposit.amount or 0))
                if deposit_amount > 0 and damage_fee_total >= deposit_amount:
                    deposit.status = 'Forfeited'
                    deposit.notes = (
                        f"{deposit.notes or ''} Deposit forfeited: damage fee "
                        f"₱{damage_fee_total:,.2f} meets or exceeds the deposit.".strip()
                    )
                    db.session.add(deposit)

        if txn.rentals and all(r.status == 'Returned' for r in txn.rentals):
            txn.status = 'Closed'

        txn.update_totals()

        db.session.commit()
        
        success_msg = f"Successfully processed return for {items_processed} item(s)."
        if damage_fee_total > 0:
            success_msg += (
                f" Damage fee assessed: ₱{damage_fee_total:,.2f}, deducted from the deposit."
            )
        if refund_deposit and deposit_refund_amount > 0:
            success_msg += f" Net deposit refund: ₱{net_deposit_refund:,.2f}."
        flash(success_msg, "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"RETURN_ERROR | TXN: {txn_id} | {str(e)}")
        flash("An error occurred while saving the return.", "danger")

    return redirect(url_for('admin.transaction_details', id=txn.id))


@admin_bp.route('/process-primegas', methods=['POST'])
@login_required
@admin_or_staff_required
def process_primegas():
    product_id = request.form.get('product_id')
    
    try:
        quantity = int(request.form.get('quantity', 0))
    except (TypeError, ValueError):
        flash('Invalid quantity provided.', 'danger')
        return redirect(url_for('admin.transactions'))

    try:
        amount = float(request.form.get('amount', 0))
    except (TypeError, ValueError):
        flash('Invalid amount provided.', 'danger')
        return redirect(url_for('admin.transactions'))

    if not product_id or quantity <= 0 or amount < 0:
        flash('Please select a valid product, quantity, and amount.', 'warning')
        return redirect(url_for('admin.transactions'))

    tank_status = TankStatus.query.filter_by(product_id=product_id).first()

    if not tank_status:
        flash('Tank status tracking not found for this product.', 'danger')
        return redirect(url_for('admin.transactions'))

    if tank_status.empty_in_stock < quantity:
        flash(f'Insufficient empty stock. Only {tank_status.empty_in_stock} empty tanks available.', 'danger')
        return redirect(url_for('admin.transactions'))

    tank_status.empty_in_stock -= quantity
    tank_status.full_in_stock += quantity

    db.session.add(InventoryLog(
        product_id=tank_status.product_id,
        reason_code="REFILL",
        action="Primegas Tank Refill",
        quantity=0,
        balance_after=tank_status.product.stock if tank_status.product else None,
        note=(
            f"Primegas refill: {quantity} empty tank(s) converted to full. "
            f"Empty: {tank_status.empty_in_stock}, Full: {tank_status.full_in_stock}."
        ),
        user_id=current_user.id,
        user_name=getattr(current_user, 'full_name', 'System Administrator')
    ))

    new_expense = Expense(
        category="Primegas Refill",
        expense_title=f"Refilled {quantity} units",
        refill_quantity=quantity,
        amount=amount,
        description=f"Primegas transaction processing batch refill for Product ID: {product_id}",
        product_id=product_id,
        recorded_by_id=current_user.id
    )
    db.session.add(new_expense)
    
    db.session.commit()
    
    flash(f'Successfully refilled {quantity} tank(s) and recorded expense!', 'success')
    return redirect(url_for('admin.transactions'))

ADJUSTMENT_REASONS = [
    'Physical Count', 'Damaged', 'Lost', 'Return to Supplier',
    'Data Entry Error', 'Other',
]


def _apply_stock_adjustment(adjustment, reviewer):
    """Apply the count delta so movements after the count are preserved."""
    product = adjustment.product
    delta = adjustment.counted_qty - adjustment.system_qty
    balance_after = (product.stock or 0) + delta

    if product.tank_status:
        tank = product.tank_status
        tank.full_in_stock = max(0, (tank.full_in_stock or 0) + delta)
        tank.total_owned = (
            (tank.full_in_stock or 0)
            + (tank.empty_in_stock or 0)
            + (tank.rented_out or 0)
            + (tank.damaged_in_stock or 0)
        )
        balance_after = tank.full_in_stock
        db.session.add(tank)

    product.stock = max(0, (product.stock or 0) + delta)
    product.status = 'Available' if product.stock > 0 else 'Out of Stock'
    db.session.add(product)

    adjustment.status = 'Approved'
    adjustment.reviewed_by_id = reviewer.id
    adjustment.reviewed_at = datetime.utcnow()

    db.session.add(InventoryLog(
        product_id=product.id,
        reference_no=f"ADJ-{adjustment.id:05d}",
        reason_code='ADJUSTMENT',
        action=f"Physical Count — {adjustment.reason_code}",
        quantity=delta,
        balance_after=balance_after,
        note=(
            f"Counted {adjustment.counted_qty} vs system {adjustment.system_qty} "
            f"(variance {delta:+d}). {adjustment.note or ''}"
        )[:255],
        user_id=reviewer.id,
        user_name=reviewer.full_name,
    ))


@admin_bp.route('/adjustments', methods=['GET'])
@login_required
@admin_or_staff_required
@permission_required('can_update_stock')
def adjustments():
    pending = (
        StockAdjustment.query.filter_by(status='Pending')
        .order_by(StockAdjustment.requested_at.asc())
        .all()
    )
    history = (
        StockAdjustment.query.filter(StockAdjustment.status != 'Pending')
        .order_by(StockAdjustment.reviewed_at.desc(), StockAdjustment.requested_at.desc())
        .limit(25)
        .all()
    )
    products = (
        Product.query.filter(Product.status != 'Archived')
        .order_by(Product.equipment_type.asc(), Product.name.asc())
        .all()
    )
    return render_template(
        'admin/adjustments.html',
        pending=pending,
        history=history,
        products=products,
        reasons=ADJUSTMENT_REASONS,
        is_admin=(current_user.role or '').strip() == 'Administrator',
    )


@admin_bp.route('/adjustments/submit', methods=['POST'])
@login_required
@admin_or_staff_required
@permission_required('can_update_stock')
def submit_adjustment():
    product = Product.query.get_or_404(request.form.get('product_id', type=int))
    try:
        counted_qty = int(request.form.get('counted_qty', ''))
        if counted_qty < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Enter a valid non-negative counted quantity.", "danger")
        return redirect(url_for('admin.adjustments'))

    reason = request.form.get('reason_code', 'Physical Count')
    if reason not in ADJUSTMENT_REASONS:
        reason = 'Physical Count'

    system_qty = (
        (product.tank_status.full_in_stock or 0)
        if product.tank_status else (product.stock or 0)
    )
    adjustment = StockAdjustment(
        product_id=product.id,
        system_qty=system_qty,
        counted_qty=counted_qty,
        variance=counted_qty - system_qty,
        reason_code=reason,
        note=request.form.get('note', '').strip()[:255],
        requested_by_id=current_user.id,
        status='Pending',
    )
    db.session.add(adjustment)
    db.session.flush()

    # An Administrator's own count is self-approved; staff counts wait for review.
    if (current_user.role or '').strip() == 'Administrator':
        _apply_stock_adjustment(adjustment, current_user)
        message = (
            f"Adjustment for {product.name} applied immediately "
            f"(variance {adjustment.variance:+d})."
        )
    else:
        message = (
            f"Count submitted for {product.name}. An Administrator must approve it "
            f"before stock is changed."
        )

    db.session.commit()
    flash(message, "success")
    return redirect(url_for('admin.adjustments'))


@admin_bp.route('/adjustments/<int:adjustment_id>/approve', methods=['POST'])
@login_required
def approve_adjustment(adjustment_id):
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)
    adjustment = StockAdjustment.query.get_or_404(adjustment_id)
    if adjustment.status != 'Pending':
        flash("This adjustment has already been reviewed.", "info")
        return redirect(url_for('admin.adjustments'))

    _apply_stock_adjustment(adjustment, current_user)
    adjustment.review_note = request.form.get('review_note', '').strip()[:255]
    db.session.commit()
    flash(f"Adjustment for {adjustment.product.name} approved and applied.", "success")
    return redirect(url_for('admin.adjustments'))


@admin_bp.route('/adjustments/<int:adjustment_id>/reject', methods=['POST'])
@login_required
def reject_adjustment(adjustment_id):
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)
    adjustment = StockAdjustment.query.get_or_404(adjustment_id)
    if adjustment.status != 'Pending':
        flash("This adjustment has already been reviewed.", "info")
        return redirect(url_for('admin.adjustments'))

    adjustment.status = 'Rejected'
    adjustment.reviewed_by_id = current_user.id
    adjustment.reviewed_at = datetime.utcnow()
    adjustment.review_note = request.form.get('review_note', '').strip()[:255]
    db.session.commit()
    flash(f"Adjustment for {adjustment.product.name} rejected.", "info")
    return redirect(url_for('admin.adjustments'))


@admin_bp.route('/inventory-movements')
@login_required
@admin_or_staff_required
@permission_required('can_update_stock')
def inventory_movements():
    """Global stock movement log: reference, reason, user, balance (Table 15)."""
    page = request.args.get('page', 1, type=int)
    limit = min(max(request.args.get('limit', 25, type=int), 10), 100)
    product_id = request.args.get('product_id', type=int)
    reason_filter = request.args.get('reason', '').strip()
    search_query = request.args.get('q', '').strip()
    start_str = request.args.get('start_date', '').strip()
    end_str = request.args.get('end_date', '').strip()

    query = InventoryLog.query.outerjoin(Product)

    if product_id:
        query = query.filter(InventoryLog.product_id == product_id)
    if reason_filter:
        query = query.filter(InventoryLog.reason_code == reason_filter)
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(or_(
            InventoryLog.reference_no.ilike(like),
            InventoryLog.note.ilike(like),
            InventoryLog.action.ilike(like),
            InventoryLog.user_name.ilike(like),
            Product.name.ilike(like),
            Product.equipment_type.ilike(like),
        ))
    if start_str:
        try:
            query = query.filter(
                InventoryLog.created_at >= datetime.strptime(start_str, '%Y-%m-%d')
            )
        except ValueError:
            pass
    if end_str:
        try:
            exclusive_end = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(InventoryLog.created_at < exclusive_end)
        except ValueError:
            pass

    stats = query.with_entities(
        func.coalesce(
            func.sum(case((InventoryLog.quantity > 0, InventoryLog.quantity), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((InventoryLog.quantity < 0, -InventoryLog.quantity), else_=0)),
            0,
        ),
        func.count(InventoryLog.id),
    ).first()

    pagination = (
        query.order_by(InventoryLog.created_at.desc(), InventoryLog.id.desc())
        .paginate(page=page, per_page=limit, error_out=False)
    )

    products = (
        Product.query.filter(Product.status != 'Archived')
        .order_by(Product.equipment_type.asc(), Product.name.asc())
        .all()
    )
    reason_codes = [
        row[0]
        for row in db.session.query(InventoryLog.reason_code)
        .filter(InventoryLog.reason_code.isnot(None))
        .distinct()
        .order_by(InventoryLog.reason_code.asc())
        .all()
    ]

    return render_template(
        'admin/inventory_movements.html',
        pagination=pagination,
        products=products,
        reason_codes=reason_codes,
        product_id=product_id,
        reason_filter=reason_filter,
        search_query=search_query,
        start_date=start_str,
        end_date=end_str,
        current_limit=limit,
        stock_in=int(stats[0] or 0) if stats else 0,
        stock_out=int(stats[1] or 0) if stats else 0,
        total_moves=int(stats[2] or 0) if stats else 0,
    )


@admin_bp.route('/system_logs')
@limiter.exempt
@login_required
@admin_or_staff_required
@permission_required('can_view_logs')
def system_logs():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    search_query = request.args.get('q', '')
    current_type = request.args.get('type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = InventoryLog.query

    if search_query:
        query = query.filter(or_(
            InventoryLog.action.ilike(f'%{search_query}%'),
            InventoryLog.user_name.ilike(f'%{search_query}%'),
            InventoryLog.note.ilike(f'%{search_query}%'),
        ))

    if current_type:
        query = query.filter(InventoryLog.action == current_type)

    if date_from:
        try:
            from datetime import datetime
            date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(InventoryLog.created_at >= date_from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import datetime
            date_to_dt = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(InventoryLog.created_at <= date_to_dt)
        except ValueError:
            pass

    staff_filter = request.args.get('staff_id', '', type=str)
    if staff_filter:
        try:
            query = query.filter(InventoryLog.user_id == int(staff_filter))
        except (ValueError, TypeError):
            pass

    pagination = query.order_by(InventoryLog.created_at.desc()).paginate(
        page=page,
        per_page=limit,
        error_out=False
    )
    
    # Staff list for filter dropdown
    staff_list = User.query.filter(
        User.role.in_(['Staff', 'Administrator'])
    ).order_by(User.first_name).all()

    return render_template(
        'admin/system_logs.html',
        all_logs=pagination.items,
        pagination=pagination,
        current_limit=limit,
        search_query=search_query,
        current_type=current_type,
        date_from=date_from,
        date_to=date_to,
        staff_list=staff_list,
        staff_filter=staff_filter,
    )

@admin_bp.route('/logs/<int:log_id>/detail')
@login_required
@admin_or_staff_required
def log_detail(log_id):
    log = InventoryLog.query.get_or_404(log_id)
    return jsonify({
        'status':   'success',
        'action':   log.action,
        'user':     log.user_name or 'System',
        'product':  log.product.name if log.product else 'N/A',
        'asset':    log.product.asset_tag if log.product else '—',
        'quantity': log.quantity or 0,
        'note':     log.note or 'No notes.',
        'date':     log.created_at.strftime('%b %d, %Y %I:%M %p') if log.created_at else '—',
    })

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'webp'}

@admin_bp.route('/profile', methods=['GET', 'POST'])
@limiter.exempt
@login_required
@admin_or_staff_required
def profile():
    if request.method == 'POST':
        fname = request.form.get('fname', '').strip()
        lname = request.form.get('lname', '').strip()
        email = request.form.get('email', '').strip()

        if not fname or not lname or not email:
            flash('All fields are required.', 'danger')
            return redirect(url_for('admin.profile'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user and existing_user.id != current_user.id:
            flash('That email address is already in use.', 'danger')
            return redirect(url_for('admin.profile'))

        current_user.first_name = fname
        current_user.last_name = lname
        current_user.email = email

        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating your information.', 'danger')
            
        return redirect(url_for('admin.profile')) 

    return render_template("admin/profile.html")


@admin_bp.route('/profile/update-avatar', methods=['POST'])
@login_required
@admin_or_staff_required
def update_avatar():
    """Handles profile picture uploads via AJAX."""
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'}), 400
        
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        upload_folder = os.path.join(current_app.root_path, 'uploads', 'profiles')
        os.makedirs(upload_folder, exist_ok=True)

        file_ext = file.filename.rsplit('.', 1)[1].lower()
        filename = secure_filename(f"user_{current_user.id}.{file_ext}")
        filepath = os.path.join(upload_folder, filename)

        try:
            # FIXED: Checking and clearing out old image using profile_path
            if current_user.profile_path:
                old_path = os.path.join(upload_folder, current_user.profile_path)
                if os.path.exists(old_path):
                    os.remove(old_path)

            file.save(filepath)
            current_user.profile_path = filename # FIXED: Assigned to database column property
            db.session.commit()

            img_url = url_for('admin.serve_profile_pic', filename=filename)
            return jsonify({'success': True, 'img_url': img_url})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Database error or saving failed.'}), 500

    return jsonify({'success': False, 'message': 'Invalid file extension.'}), 400


@admin_bp.route('/profile/remove-avatar', methods=['POST'])
@login_required
@admin_or_staff_required
def remove_avatar():
    """Handles removing profile picture via AJAX."""
    if not current_user.profile_path:
        return jsonify({'success': True})

    upload_folder = os.path.join(current_app.root_path, 'uploads', 'profiles')
    try:
        old_path = os.path.join(upload_folder, current_user.profile_path)
        if os.path.exists(old_path):
            os.remove(old_path)

        current_user.profile_path = None # FIXED: Cleared database column property
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Could not remove image.'}), 500


@admin_bp.route('/uploads/profiles/<filename>')
@login_required
@limiter.exempt
def serve_profile_pic(filename):
    """Securely serves files from the uploads/profiles folder."""
    return send_from_directory(os.path.join(current_app.root_path, 'uploads', 'profiles'), filename)


@admin_bp.route('/reports')
@login_required
@admin_or_staff_required
@permission_required('can_view_reports')
def reports():
    from datetime import date
    from sqlalchemy import extract
 
    today = date.today()
    current_year = today.year
    current_month = today.month
 
    # ── SALES ──────────────────────────────────────────────────────────────
    total_sales_revenue = db.session.query(
        func.sum(Transaction.amount_paid)
    ).filter(Transaction.transaction_type == 'Sale').scalar() or 0
 
    total_sale_transactions = Transaction.query.filter_by(
        transaction_type='Sale'
    ).count()
 
    cancelled_orders = Transaction.query.filter_by(
        status='Cancelled'
    ).count()
 
    avg_transaction_value = round(
        float(total_sales_revenue) / total_sale_transactions, 2
    ) if total_sale_transactions > 0 else 0
 
    # Sales per month (last 6 months)
    sales_by_month = []
    sales_labels = []
    for i in range(5, -1, -1):
        from dateutil.relativedelta import relativedelta as rd
        target = today - rd(months=i)
        month_total = db.session.query(
            func.sum(Transaction.amount_paid)
        ).filter(
            Transaction.transaction_type == 'Sale',
            extract('year', Transaction.created_at) == target.year,
            extract('month', Transaction.created_at) == target.month
        ).scalar() or 0
        sales_by_month.append(float(month_total))
        sales_labels.append(target.strftime('%b'))
 
    # Top selling products by revenue
    top_products = db.session.query(
        Product.name,
        Product.equipment_type,
        func.sum(Purchase.quantity).label('units_sold'),
        func.sum(Purchase.total_price).label('revenue'),
        Product.stock,
        Product.reorder_level
    ).join(Purchase, Purchase.product_id == Product.id)\
     .group_by(Product.id)\
     .order_by(func.sum(Purchase.total_price).desc())\
     .limit(5).all()
 
    # Sales by equipment type (for donut chart)
    sales_by_category = db.session.query(
        Product.equipment_type,
        func.sum(Purchase.total_price).label('revenue')
    ).join(Purchase, Purchase.product_id == Product.id)\
     .group_by(Product.equipment_type)\
     .order_by(func.sum(Purchase.total_price).desc())\
     .limit(5).all()
 
    # ── RENTALS ────────────────────────────────────────────────────────────
    active_rentals = Rental.query.filter_by(status='Active').count()
 
    rental_revenue = db.session.query(
        func.sum(Payment.amount)
    ).join(Transaction).filter(
        Transaction.transaction_type == 'Rental',
        Payment.status == 'Completed'
    ).scalar() or 0
 
    overdue_rentals = Rental.query.filter(
        Rental.status == 'Active',
        Rental.expected_return_date < today
    ).all()
 
    returned_rentals = Rental.query.filter_by(status='Returned').count()
 
    # Rentals per month (last 6 months)
    rentals_by_month = []
    for i in range(5, -1, -1):
        target = today - rd(months=i)
        month_count = Rental.query.filter(
            extract('year', Rental.created_at) == target.year,
            extract('month', Rental.created_at) == target.month
        ).count()
        rentals_by_month.append(month_count)
 
    # ── INVENTORY ──────────────────────────────────────────────────────────
    total_inventory = db.session.query(
        func.sum(Product.stock)
    ).scalar() or 0
 
    low_stock_products = Product.query.filter(
        Product.stock <= Product.reorder_level,
        Product.stock > 0,
        Product.status != 'Archived'
    ).order_by(Product.stock.asc()).all()
 
    out_of_stock_count = Product.query.filter_by(stock=0).count()
 
    stock_health = round(
        (1 - (out_of_stock_count / total_inventory)) * 100, 1
    ) if total_inventory > 0 else 100
 
    # Stock by category
    stock_by_category = db.session.query(
        Product.equipment_type,
        func.sum(Product.stock).label('total_stock')
    ).group_by(Product.equipment_type)\
     .order_by(func.sum(Product.stock).desc())\
     .limit(6).all()
 
    # Most used items (by purchase count)
    most_used = db.session.query(
        Product.name,
        func.count(Purchase.id).label('use_count')
    ).join(Purchase, Purchase.product_id == Product.id)\
     .group_by(Product.id)\
     .order_by(func.count(Purchase.id).desc())\
     .limit(5).all()
 
    max_use = most_used[0].use_count if most_used else 1
 
    # ── CUSTOMERS ──────────────────────────────────────────────────────────
    from models.customer import Customer as CustomerModel
    total_customers = CustomerModel.query.count()
 
    new_customers_this_month = CustomerModel.query.filter(
        extract('year', CustomerModel.created_at) == current_year,
        extract('month', CustomerModel.created_at) == current_month
    ).count()
 
    customers_with_overdue = db.session.query(
        func.count(func.distinct(Rental.customer_id))
    ).filter(
        Rental.status == 'Active',
        Rental.expected_return_date < today
    ).scalar() or 0
 
    # Customer growth per month
    customer_growth = []
    for i in range(5, -1, -1):
        target = today - rd(months=i)
        count = CustomerModel.query.filter(
            extract('year', CustomerModel.created_at) == target.year,
            extract('month', CustomerModel.created_at) == target.month
        ).count()
        customer_growth.append(count)
 
    # Top customers by spending
    top_customers = db.session.query(
        CustomerModel.first_name,
        CustomerModel.last_name,
        func.count(Transaction.id).label('txn_count'),
        func.sum(Transaction.amount_paid).label('total_spent'),
        func.max(Transaction.created_at).label('last_activity')
    ).join(Transaction, Transaction.customer_id == CustomerModel.id)\
     .group_by(CustomerModel.id)\
     .order_by(func.sum(Transaction.amount_paid).desc())\
     .limit(5).all()
 
    # Returning customers (transacted more than once)
    returning_count = db.session.query(
        func.count()
    ).select_from(
        db.session.query(Transaction.customer_id)
        .group_by(Transaction.customer_id)
        .having(func.count(Transaction.id) > 1)
        .subquery()
    ).scalar() or 0
 
    returning_rate = round(
        (returning_count / total_customers) * 100, 1
    ) if total_customers > 0 else 0
 
    # ── FINANCIAL ──────────────────────────────────────────────────────────
    # Gross Revenue = completed sales revenue + completed rental revenue
    sales_revenue_total = db.session.query(
        func.sum(Payment.amount)
    ).join(Transaction).filter(
        Transaction.transaction_type == 'Sale',
        Payment.status == 'Completed'
    ).scalar() or Decimal('0')
 
    rental_revenue_total = db.session.query(
        func.sum(Payment.amount)
    ).join(Transaction).filter(
        Transaction.transaction_type == 'Rental',
        Payment.status == 'Completed'
    ).scalar() or Decimal('0')
 
    gross_revenue = float(sales_revenue_total) + float(rental_revenue_total)
 
    # Cost of Sales = expenses in COST_OF_SALES_CATEGORIES
    cos_rows = db.session.query(
        Expense.category,
        func.sum(Expense.amount).label('total')
    ).filter(
        Expense.category.in_(list(COST_OF_SALES_CATEGORIES))
    ).group_by(Expense.category)\
     .order_by(func.sum(Expense.amount).desc()).all()
 
    cost_of_sales = float(sum(row.total for row in cos_rows) or 0)
 
    # Gross Profit
    gross_profit = gross_revenue - cost_of_sales
 
    # Operating Expenses = expenses in OPERATING_EXPENSE_CATEGORIES
    opex_rows = db.session.query(
        Expense.category,
        func.sum(Expense.amount).label('total')
    ).filter(
        Expense.category.in_(list(OPERATING_EXPENSE_CATEGORIES))
    ).group_by(Expense.category)\
     .order_by(func.sum(Expense.amount).desc()).all()
 
    operating_expenses = float(sum(row.total for row in opex_rows) or 0)
 
    # Net Profit and Profit Margin
    net_profit = gross_profit - operating_expenses
 
    profit_margin = round(
        (net_profit / gross_revenue) * 100, 1
    ) if gross_revenue > 0 else 0
 
    # Operating Expense breakdown dict for the table
    opex_breakdown = {row.category: float(row.total) for row in opex_rows}
    opex_total = operating_expenses if operating_expenses > 0 else 1  
 
    opex_breakdown_list = []
    for row in opex_rows:
        opex_breakdown_list.append({
            'category': row.category,
            'amount': float(row.total),
            'pct': round(float(row.total) / opex_total * 100, 1)
        })
 
    # Cost of Sales breakdown
    cos_breakdown_list = []
    cos_total = cost_of_sales if cost_of_sales > 0 else 1
    for row in cos_rows:
        cos_breakdown_list.append({
            'category': row.category,
            'amount': float(row.total),
            'pct': round(float(row.total) / cos_total * 100, 1)
        })
 
    # ── CHART DATA ─────────────────────────────────────────────────────────
    # Monthly: Revenue, Cost of Sales, Operating Expenses, Net Profit (last 6 months)
    revenue_by_month    = []
    cos_by_month        = []
    opex_by_month       = []
    net_profit_by_month = []
    expenses_by_month   = []   
 
    for i in range(5, -1, -1):
        target = today - rd(months=i)
 
        rev_m = db.session.query(func.sum(Payment.amount)).join(Transaction).filter(
            Payment.status == 'Completed',
            extract('year',  Payment.created_at) == target.year,
            extract('month', Payment.created_at) == target.month,
        ).scalar() or 0
 
        cos_m = db.session.query(func.sum(Expense.amount)).filter(
            Expense.category.in_(list(COST_OF_SALES_CATEGORIES)),
            extract('year',  Expense.date_incurred) == target.year,
            extract('month', Expense.date_incurred) == target.month,
        ).scalar() or 0
 
        opex_m = db.session.query(func.sum(Expense.amount)).filter(
            Expense.category.in_(list(OPERATING_EXPENSE_CATEGORIES)),
            extract('year',  Expense.date_incurred) == target.year,
            extract('month', Expense.date_incurred) == target.month,
        ).scalar() or 0
 
        exp_m = float(cos_m) + float(opex_m)
 
        revenue_by_month.append(float(rev_m))
        cos_by_month.append(float(cos_m))
        opex_by_month.append(float(opex_m))
        net_profit_by_month.append(round(float(rev_m) - exp_m, 2))
        expenses_by_month.append(exp_m)
 
    # Expense breakdown by category (all categories, for donut)
    expense_by_category = db.session.query(
        Expense.category,
        func.sum(Expense.amount).label('total')
    ).group_by(Expense.category)\
     .order_by(func.sum(Expense.amount).desc())\
     .all()
 
    # COS vs OPEX for stacked/grouped chart
    cos_vs_opex_labels  = ['Cost of Sales', 'Operating Expenses']
    cos_vs_opex_data    = [cost_of_sales, operating_expenses]
 
    # Recent transactions for financial tab
    recent_transactions = Transaction.query.order_by(
        Transaction.created_at.desc()
    ).limit(5).all()
    
    # ── Equipment P&L ─────────────────────────────────────────────────────
    # Get all products
    all_equipment_products = Product.query.filter_by(is_active=True).all()

    equipment_pl = []
    for prod in all_equipment_products:

        # Total acquisition cost from linked expenses
        total_spent = float(
            db.session.query(func.sum(Expense.amount))
            .filter(Expense.product_id == prod.id)
            .scalar() or 0
        )

        # Sale income
        sale_income = float(
            db.session.query(func.sum(Purchase.total_price))
            .filter(Purchase.product_id == prod.id)
            .scalar() or 0
        )

        # Rental income — sum of completed payments linked to rentals of this product
        rental_income = float(
            db.session.query(func.sum(Payment.amount))
            .join(Transaction, Payment.transaction_id == Transaction.id)
            .join(Rental, Rental.transaction_id == Transaction.id)
            .filter(
                Rental.product_id == prod.id,
                Payment.status == 'Completed'
            )
            .scalar() or 0
        )

        # Units acquired — sum of quantities from acquisition expenses
        units_acquired = int(
            db.session.query(func.sum(InventoryLog.quantity))
            .filter(
                InventoryLog.product_id == prod.id,
                InventoryLog.action.in_(['Initial Stock Entry', 'Restock'])
            )
            .scalar() or 0
        )

        total_income = sale_income + rental_income
        net = total_income - total_spent

        # Only include products that have some data
        if total_spent > 0 or total_income > 0:
            equipment_pl.append({
                'name': prod.name,
                'equipment_type': prod.equipment_type,
                'units_acquired': units_acquired,
                'total_spent': total_spent,
                'sale_income': sale_income,
                'rental_income': rental_income,
                'total_income': total_income,
                'net': net,
            })

    # Sort by total income descending
    equipment_pl.sort(key=lambda x: x['total_income'], reverse=True)
 
    return render_template(
        "admin/reports.html",
 
        # Sales
        total_sales_revenue=total_sales_revenue,
        total_sale_transactions=total_sale_transactions,
        avg_transaction_value=avg_transaction_value,
        cancelled_orders=cancelled_orders,
        sales_by_month=sales_by_month,
        sales_labels=sales_labels,
        top_products=top_products,
        sales_by_category=sales_by_category,
 
        # Rentals
        active_rentals=active_rentals,
        rental_revenue=rental_revenue,
        overdue_rentals=overdue_rentals,
        returned_rentals=returned_rentals,
        rentals_by_month=rentals_by_month,
 
        # Inventory
        total_inventory=total_inventory,
        low_stock_products=low_stock_products,
        out_of_stock_count=out_of_stock_count,
        stock_health=stock_health,
        stock_by_category=stock_by_category,
        most_used=most_used,
        max_use=max_use,
 
        # Customers
        total_customers=total_customers,
        new_customers_this_month=new_customers_this_month,
        customers_with_overdue=customers_with_overdue,
        returning_rate=returning_rate,
        customer_growth=customer_growth,
        top_customers=top_customers,
        returning_count=returning_count,
 
        # Financial — summary
        gross_revenue=gross_revenue,
        cost_of_sales=cost_of_sales,
        gross_profit=gross_profit,
        operating_expenses=operating_expenses,
        net_profit=net_profit,
        profit_margin=profit_margin,
 
        # Financial — breakdowns
        opex_breakdown_list=opex_breakdown_list,
        cos_breakdown_list=cos_breakdown_list,
 
        # Financial — charts
        revenue_by_month=revenue_by_month,
        cos_by_month=cos_by_month,
        opex_by_month=opex_by_month,
        net_profit_by_month=net_profit_by_month,
        expenses_by_month=expenses_by_month,
        expense_by_category=expense_by_category,
        cos_vs_opex_labels=cos_vs_opex_labels,
        cos_vs_opex_data=cos_vs_opex_data,
 
        # Shared
        recent_transactions=recent_transactions,
        month_labels=sales_labels,
        total_expenses=cost_of_sales + operating_expenses,  # kept for compat
 
        # Chart datasets serialisable
        sales_by_month_json=sales_by_month,
        
        # Equipment P&L
        equipment_pl=equipment_pl,
    )

# Expenses ════════════════════════════════════════════════════════════════════════

@admin_bp.route('/reports/export/<report_type>')
@login_required
@admin_or_staff_required
@permission_required('can_view_reports')
def export_report(report_type):
    """CSV/Excel exports for sales, rentals, low stock, tanks and movements."""
    if report_type not in {
        'sales', 'rentals', 'inventory', 'low-stock', 'tanks',
        'movements', 'supplier',
    }:
        abort(404)

    start_dt, end_dt = parse_range(request.args)

    if report_type == 'sales':
        wb = build_sales_export(start_dt, end_dt)
    elif report_type == 'rentals':
        wb = build_rentals_export(start_dt, end_dt)
    elif report_type == 'inventory':
        wb = build_inventory_export(low_only=False)
    elif report_type == 'low-stock':
        wb = build_inventory_export(low_only=True)
    elif report_type == 'tanks':
        wb = build_tank_export()
    elif report_type == 'movements':
        wb = build_movements_export(start_dt, end_dt)
    else:
        wb = build_supplier_export(start_dt, end_dt)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return xlsx_response(wb, f"caremed_{report_type}_{stamp}.xlsx")


@admin_bp.route('/expenses')
@login_required
@admin_or_staff_required
@permission_required('can_manage_expenses')
def expenses():
    from sqlalchemy import extract
    from datetime import date, datetime as dt

    today = date.today()

    # ── Date range mode ─────────────────────────────────────────────────────
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str   = request.args.get('end_date', '').strip()
    use_range = bool(start_date_str and end_date_str)

    start_date = end_date = None
    if use_range:
        try:
            start_date = dt.strptime(start_date_str, '%Y-%m-%d').date()
            end_date   = dt.strptime(end_date_str, '%Y-%m-%d').date()
            if start_date > end_date:
                start_date, end_date = end_date, start_date
        except ValueError:
            use_range = False

    # ── Month/Year mode (default) ───────────────────────────────────────────
    year  = request.args.get('year',  today.year,  type=int)
    month = request.args.get('month', today.month, type=int)
    category_filter = request.args.get('category', '')

    # ── Build expense query ─────────────────────────────────────────────────
    query = Expense.query

    if use_range:
        query = query.filter(
            Expense.date_incurred >= start_date,
            Expense.date_incurred <= end_date,
        )
    else:
        query = query.filter(
            extract('year',  Expense.date_incurred) == year,
            extract('month', Expense.date_incurred) == month,
        )

    if category_filter:
        query = query.filter(Expense.category == category_filter)

    expenses_list = query.order_by(Expense.date_incurred.desc()).all()

    # ── Category totals (for charts) ────────────────────────────────────────
    def _period_filter(q):
        if use_range:
            return q.filter(
                Expense.date_incurred >= start_date,
                Expense.date_incurred <= end_date,
            )
        return q.filter(
            extract('year',  Expense.date_incurred) == year,
            extract('month', Expense.date_incurred) == month,
        )

    cat_query = _period_filter(
        db.session.query(
            Expense.category,
            func.sum(Expense.amount).label('total')
        )
    ).group_by(Expense.category)\
     .order_by(func.sum(Expense.amount).desc())

    category_totals = cat_query.all()

    # ── Financial metrics for the period ────────────────────────────────────
    # Cost of Sales
    cos_total = float(
        _period_filter(
            db.session.query(func.sum(Expense.amount))
            .filter(Expense.category.in_(list(COST_OF_SALES_CATEGORIES)))
        ).scalar() or 0
    )

    # Operating Expenses
    opex_total = float(
        _period_filter(
            db.session.query(func.sum(Expense.amount))
            .filter(Expense.category.in_(list(OPERATING_EXPENSE_CATEGORIES)))
        ).scalar() or 0
    )

    total_expenses = cos_total + opex_total

    # Gross Revenue for the period (completed standard payments)
    rev_query = db.session.query(func.sum(Payment.amount)).join(Transaction).filter(
        Payment.status == 'Completed'
    )
    if use_range:
        rev_query = rev_query.filter(
            Payment.created_at >= dt.combine(start_date, dt.min.time()),
            Payment.created_at <= dt.combine(end_date, dt.max.time()),
        )
    else:
        rev_query = rev_query.filter(
            extract('year',  Payment.created_at) == year,
            extract('month', Payment.created_at) == month,
        )
    transaction_revenue = float(rev_query.scalar() or 0)

    # Gross Revenue from Refill transactions
    refill_rev_query = db.session.query(func.sum(Transaction.total_amount)).filter(
        Transaction.transaction_type == 'Refill'
    )
    if use_range:
        refill_rev_query = refill_rev_query.filter(
            Transaction.created_at >= dt.combine(start_date, dt.min.time()),
            Transaction.created_at <= dt.combine(end_date, dt.max.time()),
        )
    else:
        refill_rev_query = refill_rev_query.filter(
            extract('year',  Transaction.created_at) == year,
            extract('month', Transaction.created_at) == month,
        )
    refill_revenue = float(refill_rev_query.scalar() or 0)

    gross_revenue = transaction_revenue + refill_revenue

    gross_profit     = gross_revenue - cos_total
    net_profit       = gross_profit  - opex_total
    profit_margin    = round((net_profit / gross_revenue) * 100, 1) if gross_revenue > 0 else 0

    # ── Last 6-month trend (always month-based) ─────────────────────────────
    from dateutil.relativedelta import relativedelta as rd
    trend_labels   = []
    trend_expense  = []   # total expenses (COS + OPEX)
    trend_cos      = []
    trend_opex     = []
    trend_revenue  = []
    trend_net      = []

    for i in range(5, -1, -1):
        target = today - rd(months=i)
        exp = float(db.session.query(func.sum(Expense.amount)).filter(
            extract('year',  Expense.date_incurred) == target.year,
            extract('month', Expense.date_incurred) == target.month,
        ).scalar() or 0)
        cos_m = float(db.session.query(func.sum(Expense.amount)).filter(
            Expense.category.in_(list(COST_OF_SALES_CATEGORIES)),
            extract('year',  Expense.date_incurred) == target.year,
            extract('month', Expense.date_incurred) == target.month,
        ).scalar() or 0)
        opex_m = float(db.session.query(func.sum(Expense.amount)).filter(
            Expense.category.in_(list(OPERATING_EXPENSE_CATEGORIES)),
            extract('year',  Expense.date_incurred) == target.year,
            extract('month', Expense.date_incurred) == target.month,
        ).scalar() or 0)
        
        rev_m = float(db.session.query(func.sum(Payment.amount)).join(Transaction).filter(
            Payment.status == 'Completed',
            extract('year',  Payment.created_at) == target.year,
            extract('month', Payment.created_at) == target.month,
        ).scalar() or 0)

        refill_m = float(db.session.query(func.sum(Transaction.total_amount)).filter(
            Transaction.transaction_type == 'Refill',
            extract('year',  Transaction.created_at) == target.year,
            extract('month', Transaction.created_at) == target.month,
        ).scalar() or 0)

        total_rev_m = rev_m + refill_m

        trend_labels.append(target.strftime('%b %Y'))
        trend_expense.append(exp)
        trend_cos.append(cos_m)
        trend_opex.append(opex_m)
        trend_revenue.append(total_rev_m)
        trend_net.append(round(total_rev_m - exp, 2))

    # ── Category type lookup (for table badges) ─────────────────────────────
    def category_type(cat):
        if cat in COST_OF_SALES_CATEGORIES:
            return 'cos'
        if cat in OPERATING_EXPENSE_CATEGORIES:
            return 'opex'
        return 'other'

    months = [
        (1,'January'),(2,'February'),(3,'March'),(4,'April'),
        (5,'May'),(6,'June'),(7,'July'),(8,'August'),
        (9,'September'),(10,'October'),(11,'November'),(12,'December')
    ]

    return render_template(
        'admin/expenses.html',
        # Expense records
        expenses=expenses_list,
        category_totals=category_totals,
        category_type=category_type,

        # Period totals
        total_this_month=total_expenses,
        revenue_this_month=gross_revenue,

        # Financial summary
        gross_revenue=gross_revenue,
        cost_of_sales=cos_total,
        gross_profit=gross_profit,
        operating_expenses=opex_total,
        net_profit=net_profit,
        profit_margin=profit_margin,

        # Trend charts
        trend_labels=trend_labels,
        trend_expense=trend_expense,
        trend_cos=trend_cos,
        trend_opex=trend_opex,
        trend_revenue=trend_revenue,
        trend_net=trend_net,

        # Filter state
        all_categories=ALL_EXPENSE_CATEGORIES_ORDERED,
        category_filter=category_filter,
        months=months,
        current_year=year,
        current_month=month,
        use_range=use_range,
        start_date=start_date,
        end_date=end_date,
        today=today,

        # Sets for Jinja checks
        cos_categories=COST_OF_SALES_CATEGORIES,
        opex_categories=OPERATING_EXPENSE_CATEGORIES,
    )
    
@admin_bp.route('/expenses/add', methods=['POST'])
@login_required
@admin_or_staff_required
def add_expense():
    if current_user.role.strip() != 'Administrator':
        flash("Only Administrators can record expenses.", "danger")
        return redirect(url_for('admin.expenses'))
    
    from datetime import datetime
    try:
        category    = request.form.get('category', '').strip()
        expense_title = request.form.get('expense_title', '').strip()
        amount_raw  = request.form.get('amount', '0').replace(',', '').strip()
        description = request.form.get('description', '').strip()
        date_str    = request.form.get('date_incurred', '').strip()
 
        if not category or not amount_raw or not expense_title:
            flash('Category, expense name, and amount are required.', 'error')
            return redirect(request.referrer)
 
        amount = Decimal(amount_raw)
        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(request.referrer)
 
        date_incurred = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.utcnow().date()
 
        # Handle receipt attachment
        attachment_path = None
        file = request.files.get('attachment')
        if file and file.filename:
            ext = os.path.splitext(secure_filename(file.filename))[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.pdf']:
                flash('Invalid file type. Use JPG, PNG, WebP, or PDF.', 'error')
                return redirect(request.referrer)
            filename = f"exp_{uuid.uuid4().hex[:12]}{ext}"
            folder = os.path.join(current_app.root_path, 'static', 'uploads', 'expenses')
            os.makedirs(folder, exist_ok=True)
            file.save(os.path.join(folder, filename))
            attachment_path = f'uploads/expenses/{filename}'
 
        new_expense = Expense(
            category=category,
            expense_title=expense_title,
            amount=amount,
            description=description,
            date_incurred=date_incurred,
            attachment_path=attachment_path,
            recorded_by_id=current_user.id,
        )
        db.session.add(new_expense)
 
        log = InventoryLog(
            action='Expense Recorded',
            note=f'{expense_title} ({category}) — ₱{amount:,.2f}: {description[:80] if description else "No notes"}',
            user_id=current_user.id,
            user_name=current_user.full_name,
        )
        db.session.add(log)
        db.session.commit()
 
        flash(f'Expense of ₱{amount:,.2f} recorded successfully.', 'success')
 
    except (InvalidOperation, ValueError):
        db.session.rollback()
        flash('Invalid amount format.', 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'ADD_EXPENSE_ERROR: {e}')
        flash('An error occurred while saving the expense.', 'error')
 
    return redirect(request.referrer or url_for('admin.expenses',
                                             year=request.form.get('year', ''),
                                             month=request.form.get('month', '')))
 
 
@admin_bp.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def delete_expense(expense_id):
    if current_user.role.strip() != 'Administrator':
        flash("Only Administrators can delete expenses.", "danger")
        return redirect(url_for('admin.expenses'))
    
    expense = Expense.query.get_or_404(expense_id)
    try:
        # Delete attachment file if it exists
        if expense.attachment_path:
            full_path = os.path.join(current_app.root_path, 'static', expense.attachment_path)
            if os.path.exists(full_path):
                os.remove(full_path)
 
        log = InventoryLog(
            action='Expense Deleted',
            note=f'Deleted expense: {expense.category} — ₱{expense.amount:,.2f}',
            user_id=current_user.id,
            user_name=current_user.full_name,
        )
        db.session.add(log)
        db.session.delete(expense)
        db.session.commit()
        flash('Expense deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'DELETE_EXPENSE_ERROR: {e}')
        flash('Failed to delete expense.', 'error')
 
    return redirect(request.referrer or url_for('admin.expenses'))
 
 
@admin_bp.route('/expenses/edit/<int:expense_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def edit_expense(expense_id):
    if current_user.role.strip() != 'Administrator':
        flash("Only Administrators can edit expenses.", "danger")
        return redirect(url_for('admin.expenses'))
    
    from datetime import datetime
    expense = Expense.query.get_or_404(expense_id)
    try:
        expense.category      = request.form.get('category', expense.category).strip()
        expense.expense_title = request.form.get('expense_title', expense.expense_title).strip()
        expense.description   = request.form.get('description', '').strip()
        date_str = request.form.get('date_incurred', '')
        if date_str:
            expense.date_incurred = datetime.strptime(date_str, '%Y-%m-%d').date()
 
        amount_raw = request.form.get('amount', '0').replace(',', '').strip()
        expense.amount = Decimal(amount_raw)
 
        db.session.commit()
        flash('Expense updated.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'EDIT_EXPENSE_ERROR: {e}')
        flash('Failed to update expense.', 'error')
 
    return redirect(request.referrer or url_for('admin.expenses'))


# ── Security Dashboard 
@admin_bp.route('/security')
@limiter.exempt
@login_required
def security_dashboard():
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))

    show_archived = request.args.get('archived') == '1'
    log_scope = SecurityLog.query.filter(SecurityLog.is_archived.is_(show_archived))
    logs = log_scope.order_by(SecurityLog.created_at.desc()).limit(500).all()
    blocked = BlockedIP.query.filter_by(is_active=True).order_by(BlockedIP.blocked_at.desc()).all()
 
    total_logs        = log_scope.count()
    suspicious_count  = log_scope.filter_by(is_suspicious=True).count()
    blocked_count     = BlockedIP.query.filter_by(is_active=True).count()
    rate_limit_count  = log_scope.filter_by(event_type="Rate Limit Violation").count()
 
    failed_count      = log_scope.filter(SecurityLog.event_type.ilike("%failed%")).count()
    locked_count      = log_scope.filter(SecurityLog.event_type.ilike("%lock%")).count()
    blocked_ip_count  = log_scope.filter(SecurityLog.event_type.ilike("%block%")).count()
    bot_count         = log_scope.filter_by(event_type="Bot Detected").count()
    archived_count    = SecurityLog.query.filter_by(is_archived=True).count()
 
    # ── Admin Activity tab ────────────────────────────────────────────────
    # All event types that belong to admin activity monitoring
    admin_event_types = [
        'Admin Login',
        'Admin Login — New Device',
        'Admin Logout',
        'Admin Session Expired',
        'Admin Failed Login',
    ]

    staff_event_types = [
        'Staff Login',
        'Staff Login — New Device',
        'Staff Logout',
        'Staff Session Expired',
        'Staff Failed Login',
        'Staff Action',
    ]
 
    admin_logs = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(admin_event_types),
    ).order_by(SecurityLog.created_at.desc()).limit(200).all()

    admin_activity_count = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(admin_event_types),
    ).count()

    admin_login_count = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(['Admin Login', 'Admin Login — New Device']),
    ).count()

    admin_logout_count = SecurityLog.query.filter_by(
        event_type='Admin Logout', is_archived=False
    ).count()

    admin_expired_count = SecurityLog.query.filter_by(
        event_type='Admin Session Expired', is_archived=False
    ).count()

    admin_failed_count = SecurityLog.query.filter_by(
        event_type='Admin Failed Login', is_archived=False
    ).count()

    # ── Staff Activity ─────────────────────────────────────────────────────
    staff_logs = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(staff_event_types),
    ).order_by(SecurityLog.created_at.desc()).limit(200).all()

    staff_activity_count = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(staff_event_types),
    ).count()

    staff_login_count = SecurityLog.query.filter(
        SecurityLog.is_archived == False,
        SecurityLog.event_type.in_(['Staff Login', 'Staff Login — New Device']),
    ).count()

    staff_logout_count = SecurityLog.query.filter_by(
        event_type='Staff Logout', is_archived=False
    ).count()

    staff_action_count = SecurityLog.query.filter_by(
        event_type='Staff Action', is_archived=False
    ).count()

    # ── All staff actions from InventoryLog (what they did) ───────────────
    staff_users = User.query.filter_by(role='Staff').all()
    staff_user_ids = [u.id for u in staff_users]

    staff_activity_logs = InventoryLog.query.filter(
        InventoryLog.user_id.in_(staff_user_ids)
    ).order_by(InventoryLog.created_at.desc()).limit(200).all()
 
    return render_template(
        'admin/security_dashboard.html',
        logs=logs,
        blocked=blocked,
        total_logs=total_logs,
        suspicious_count=suspicious_count,
        blocked_count=blocked_count,
        rate_limit_count=rate_limit_count,
        failed_count=failed_count,
        locked_count=locked_count,
        blocked_ip_count=blocked_ip_count,
        bot_count=bot_count,
        # admin activity
        admin_logs=admin_logs,
        admin_activity_count=admin_activity_count,
        admin_login_count=admin_login_count,
        admin_logout_count=admin_logout_count,
        admin_expired_count=admin_expired_count,
        admin_failed_count=admin_failed_count,
        # staff activity
        staff_logs=staff_logs,
        staff_activity_count=staff_activity_count,
        staff_login_count=staff_login_count,
        staff_logout_count=staff_logout_count,
        staff_action_count=staff_action_count,
        staff_activity_logs=staff_activity_logs,
        staff_members=staff_users,
        show_archived=show_archived,
        archived_count=archived_count,
    )


# ── Block an IP (manual or auto via JS) 
@admin_bp.route('/security/block-ip', methods=['POST'])
@login_required
@admin_or_staff_required
def block_ip():
    ip = request.form.get('ip_address', '').strip()
    reason = request.form.get('reason', 'Manually blocked by admin').strip()
    duration_hours = request.form.get('duration_hours', '').strip()
 
    if not ip:
        flash("IP address is required.", "error")
        return redirect(url_for('admin.security_dashboard'))
 
    from datetime import datetime, timedelta
 
    blocked_until = None
    if duration_hours:
        try:
            h = int(duration_hours)
            if h > 0:
                blocked_until = datetime.utcnow() + timedelta(hours=h)
        except ValueError:
            pass
 
    existing = BlockedIP.query.filter_by(ip_address=ip).first()
    if existing:
        existing.is_active = True
        existing.reason = reason
        existing.blocked_until = blocked_until
        existing.blocked_at = datetime.utcnow()
        existing.blocked_by = current_user.id
    else:
        entry = BlockedIP(
            ip_address=ip,
            reason=reason,
            blocked_until=blocked_until,
            is_active=True,
            blocked_by=current_user.id
        )
        db.session.add(entry)
 
    # Log the manual block in security logs
    log = SecurityLog(
        ip_address=ip,
        event_type="IP Blocked",
        description=f"Admin manually blocked IP. Reason: {reason}",
        user_id=current_user.id,
        user_email=current_user.email,
        is_suspicious=True
    )
    db.session.add(log)
 
    try:
        db.session.commit()
        flash(f"IP {ip} has been blocked successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error blocking IP: {str(e)}", "error")
 
    return redirect(url_for('admin.security_dashboard'))
 
 
# ── Unblock an IP 
@admin_bp.route('/security/unblock/<int:block_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def unblock_ip(block_id):
    entry = BlockedIP.query.get_or_404(block_id)
    entry.is_active = False
 
    log = SecurityLog(
        ip_address=entry.ip_address,
        event_type="IP Unblocked",
        description=f"Admin unblocked IP {entry.ip_address}",
        user_id=current_user.id,
        user_email=current_user.email,
        is_suspicious=False
    )
    db.session.add(log)
 
    try:
        db.session.commit()
        flash(f"IP {entry.ip_address} has been unblocked.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error unblocking IP: {str(e)}", "error")
 
    return redirect(url_for('admin.security_dashboard'))
 
 
# ── Archive a single security log (never hard-delete)
@admin_bp.route('/security/delete-log/<int:log_id>', methods=['POST'])
@login_required
@admin_or_staff_required
def delete_security_log(log_id):
    if (current_user.role or '').strip() != 'Administrator':
        return jsonify({
            "success": False,
            "message": "Administrator access required to archive audit logs."
        }), 403

    log = SecurityLog.query.get_or_404(log_id)
    if log.is_archived:
        return jsonify({
            "success": True,
            "message": "This log is already archived."
        })

    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or request.form.get('reason') or '').strip()
    if not reason:
        return jsonify({
            "success": False,
            "message": "A written reason is required before archiving an audit log."
        }), 400

    try:
        log.is_archived = True
        log.archived_at = datetime.utcnow()
        log.archived_by = current_user.email
        log.archive_reason = reason[:255]
        db.session.add(log)
        db.session.add(SecurityLog(
            event_type="Audit Log Archived",
            description=(
                f"Security log #{log.id} ({log.event_type or 'Unknown event'}) "
                f"archived by Administrator. Reason: {reason[:255]}"
            ),
            user_id=current_user.id,
            user_email=current_user.email,
            severity="High",
        ))
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Log archived. The record remains permanently in the database."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
 
 
# ── Archive ALL active security logs (never hard-delete)
@admin_bp.route('/security/clear-logs', methods=['POST'])
@login_required
@admin_or_staff_required
def clear_security_logs():
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)

    reason = (
        request.form.get('reason')
        or request.form.get('archive_reason')
        or ''
    ).strip()
    if not reason:
        flash("A written reason is required before archiving the audit logs.", "danger")
        return redirect(url_for('admin.security_dashboard'))

    try:
        active_query = SecurityLog.query.filter_by(is_archived=False)
        count = active_query.count()
        if count == 0:
            flash("There are no active security logs to archive.", "info")
            return redirect(url_for('admin.security_dashboard'))

        active_query.update(
            {
                'is_archived': True,
                'archived_at': datetime.utcnow(),
                'archived_by': current_user.email,
                'archive_reason': reason[:255],
            },
            synchronize_session=False,
        )
        db.session.add(SecurityLog(
            event_type="Audit Logs Archived",
            description=(
                f"{count} security log(s) archived by Administrator. "
                f"Reason: {reason[:255]}"
            ),
            user_id=current_user.id,
            user_email=current_user.email,
            severity="High",
        ))
        db.session.commit()
        flash(
            f"{count} security log(s) archived. The records remain permanently "
            "in the database.",
            "success",
        )
    except Exception as e:
        db.session.rollback()
        flash(f"Error archiving logs: {str(e)}", "error")
    return redirect(url_for('admin.security_dashboard'))

# ── Backup Management ──────────────────────────
@admin_bp.route('/backup')
@login_required
def backup_page():
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/backup.html')


@admin_bp.route('/backup/data')
@login_required
def backup_data():
    if current_user.role.strip() != 'Administrator':
        return jsonify({'error': 'Unauthorized'}), 403
    
    backup_dir = 'backups'
    os.makedirs(backup_dir, exist_ok=True)
    
    backups = []
    with os.scandir(backup_dir) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith('.sql'):
                stats = entry.stat()
                backups.append({
                    'filename': entry.name,
                    'size': round(stats.st_size / (1024 * 1024), 2),
                    'created_at': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })

    backups = sorted(backups, key=lambda x: x['created_at'], reverse=True)
    return jsonify(backups)

@admin_bp.route('/backup/create', methods=['POST'])
@login_required
def create_manual_backup():
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    success, result = create_backup(triggered_by='admin')

    try:
        log = SecurityLog(
            ip_address=request.remote_addr,
            event_type="Manual Backup Created" if success else "Backup Failed",
            description=f"Admin triggered manual backup. Result: {result}",
            user_id=current_user.id,
            user_email=current_user.email,
            user_agent=request.headers.get('User-Agent', 'Unknown')[:255],
            severity='Low',
            is_suspicious=False
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()

    if success:
        flash(f"Backup created successfully: {result}", "success")
    else:
        flash(f"Backup failed: {result}", "error")

    return redirect(url_for('admin.backup_page'))


@admin_bp.route('/backup/download/<filename>')
@login_required
def download_backup(filename):
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    # Prevent path traversal attack
    if '..' in filename or '/' in filename or '\\' in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for('admin.backup_page'))

    filepath = os.path.join('backups', filename)
    if not os.path.exists(filepath):
        flash("Backup file not found.", "error")
        return redirect(url_for('admin.backup_page'))

    try:
        log = SecurityLog(
            ip_address=request.remote_addr,
            event_type="Backup Downloaded",
            description=f"Admin downloaded backup: {filename}",
            user_id=current_user.id,
            user_email=current_user.email,
            severity='Low',
            is_suspicious=False
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/sql')


from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError
# If you need to exempt it, import your application's csrf instance like this:
# from your_app import csrf

@admin_bp.route('/backup/delete/<filename>', methods=['POST'])
@login_required
# @csrf.exempt 
def delete_backup(filename):
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
 
    token = request.headers.get('X-CSRFToken') or request.form.get('csrf_token')
    try:
        validate_csrf(token)
    except ValidationError:
        flash("CSRF token invalid or missing.", "error")
        return redirect(url_for('admin.backup_page'))
    
    if '..' in filename or '/' in filename or '\\' in filename:
        flash("Invalid filename.", "error")
        return redirect(url_for('admin.backup_page'))

    filepath = os.path.join('backups', filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f"Backup deleted successfully.", "success")
    else:
        flash("Backup file not found.", "error")

    return redirect(url_for('admin.backup_page'))


def _build_notifications():

    from models.product import PaymentProof, RentalInvoice
    from models.customer import Customer
    from datetime import timedelta, date

    today = date.today()
    soon  = today + timedelta(days=5)
    notifications = []

    # ── 1. RENTALS WITH OVERDUE PAYMENT ───────────────────────────────────
    overdue_payment_txns = db.session.query(Transaction).join(
        Rental, Rental.transaction_id == Transaction.id
    ).filter(
        Transaction.transaction_type == 'Rental',
        Transaction.balance_due > 0,
        Transaction.status == 'Open',
        Rental.start_date <= today
    ).distinct().all()

    overdue_payment_count = len(overdue_payment_txns)

    if overdue_payment_count > 0:
        notifications.append({
            "id": "overdue_payments",
            "type": "error",
            "icon": "assignment_late",
            "title": f"{overdue_payment_count} Rental{'s' if overdue_payment_count > 1 else ''} with Overdue Payment{'s' if overdue_payment_count > 1 else ''}",
            "message": "Click to view and collect outstanding rental payments.",
            "link": "/admin/transactions?type=Rental&status=overdue_payment"
        })

    # ── 2. RENTALS EXPIRING WITHIN 3 DAYS ─────────────────────────────────
    expiring_soon = Rental.query.filter(
        Rental.status.in_(['Active', 'Partially Returned']),
        Rental.expected_return_date >= today,
        Rental.expected_return_date <= soon
    ).all()
    expiring_count = len(expiring_soon)

    if expiring_count > 0:
        notifications.append({
            "id": "expiring_soon",
            "type": "warning",
            "icon": "event_upcoming",
            "title": f"{expiring_count} Rental{'s' if expiring_count > 1 else ''} Expiring Soon",
            "message": "Click to view rentals expiring within 5 days.",
            "link": "/admin/transactions?type=Rental&status=expiring"
        })

    # ── 3. OVERDUE RETURNS (items not returned past due date) ──────────────────
    overdue_returns = Rental.query.filter(
        Rental.status.in_(['Active', 'Partially Returned']),
        Rental.expected_return_date < today
    ).all()

    if overdue_returns:
        first_item = overdue_returns[0]
        days_overdue = (today - first_item.expected_return_date).days
        
        notifications.append({
            "id": "overdue_returns",
            "type": "error",
            "icon": "assignment_return",
            "title": f"{len(overdue_returns)} Equipment Return{'s' if len(overdue_returns) > 1 else ''} OVERDUE",
            "message": f"{len(overdue_returns)} item{'s' if len(overdue_returns) > 1 else ''} not returned. Oldest: {days_overdue} days late.",
            "link": "/admin/active-rentals?filter=overdue_return" 
        })

    # ── 3b. PARTIAL RETURNS (RULE-08) ─────────────────────────────────────
    partial_returns = Rental.query.filter(
        Rental.status == 'Partially Returned'
    ).all()

    if partial_returns:
        outstanding_units = sum(
            max(0, (rental.quantity or 0) - (rental.quantity_returned or 0))
            for rental in partial_returns
        )
        notifications.append({
            "id": "partial_returns",
            "type": "warning",
            "icon": "assignment_return",
            "title": (
                f"{len(partial_returns)} Partial Return"
                f"{'s' if len(partial_returns) > 1 else ''}"
            ),
            "message": (
                f"{outstanding_units} unit"
                f"{'s' if outstanding_units != 1 else ''} still outstanding "
                "and locked as rented."
            ),
            "link": "/admin/active-rentals?filter=partial_return",
        })

    # ── 4. UNPAID SALE TRANSACTIONS ───────────────────────────────────────
    unpaid_sales = Transaction.query.filter(
        Transaction.transaction_type == 'Sale',
        Transaction.payment_status == 'Unpaid',
        Transaction.status == 'Open'
    ).count()

    if unpaid_sales > 0:
        notifications.append({
            "id": "unpaid_sales",
            "type": "warning",
            "icon": "money_off",
            "title": f"{unpaid_sales} Unpaid Sale Transaction{'s' if unpaid_sales > 1 else ''}",
            "message": f"{unpaid_sales} sale{'s' if unpaid_sales > 1 else ''} with outstanding balance.",
            "link": "/admin/transactions?type=Sale&status=unpaid"
        })

    # ── 5. PARTIALLY PAID TRANSACTIONS ────────────────────────────────────
    partial_payments = Transaction.query.filter(
        Transaction.payment_status == 'Partially Paid',
        Transaction.status == 'Open'
    ).count()

    if partial_payments > 0:
        notifications.append({
            "id": "partial_payments",
            "type": "warning",
            "icon": "payments",
            "title": f"{partial_payments} Partially Paid Transaction{'s' if partial_payments > 1 else ''}",
            "message": f"{partial_payments} transaction{'s' if partial_payments > 1 else ''} still have remaining balances.",
            "link": "/admin/transactions?status=partial"
        })

    # ── 6. LOW STOCK ──────────────────────────────────────────────────────
    low_stock = Product.query.filter(
        Product.stock <= Product.reorder_level,
        Product.stock > 0,
        Product.status != 'Archived'
    ).all()

    if low_stock:
        names = ", ".join([p.name for p in low_stock[:3]])
        extra = f" and {len(low_stock) - 3} more" if len(low_stock) > 3 else ""
        notifications.append({
            "id": "low_stock",
            "type": "warning",
            "icon": "inventory_2",
            "title": f"{len(low_stock)} Item{'s' if len(low_stock) > 1 else ''} Running Low",
            "message": f"{names}{extra} — restock soon.",
            "link": "/admin/products?filter=low_stock"
        })

    # ── 7. OUT OF STOCK ───────────────────────────────────────────────────
    out_of_stock = Product.query.filter(
        Product.stock == 0,
        Product.status != 'Archived'
    ).count()

    if out_of_stock > 0:
        notifications.append({
            "id": "out_of_stock",
            "type": "error",
            "icon": "remove_shopping_cart",
            "title": f"{out_of_stock} Item{'s' if out_of_stock > 1 else ''} Out of Stock",
            "message": "Immediate restock required.",
            "link": "/admin/products?filter=out_of_stock"
        })

    # ── 8. ORDERS STUCK AT SUBMITTED ─────────────────────────────────────
    stuck_submitted = Transaction.query.filter(
        Transaction.tracking_status == 'SUBMITTED',
        Transaction.status == 'Open'
    ).count()

    if stuck_submitted > 0:
        notifications.append({
            "id": "stuck_submitted",
            "type": "info",
            "icon": "hourglass_top",
            "title": f"{stuck_submitted} Order{'s' if stuck_submitted > 1 else ''} Awaiting Verification",
            "message": f"{stuck_submitted} order{'s' if stuck_submitted > 1 else ''} submitted and not yet verified.",
            "link": "/admin/transactions?status=submitted"
        })

    # ── 9. PENDING CUSTOMER ID VERIFICATIONS ─────────────────────────────
    pending_verifications = Customer.query.filter(
        Customer.is_id_verified == False,
        Customer.valid_id_path != None
    ).count()

    if pending_verifications > 0:
        notifications.append({
            "id": "pending_verifications",
            "type": "info",
            "icon": "verified_user",
            "title": f"{pending_verifications} ID Verification{'s' if pending_verifications > 1 else ''} Pending",
            "message": "Customer IDs uploaded and awaiting admin review.",
            "link": "/admin/customers?filter=pending_id"
        })

    # ── 10. INACTIVE CUSTOMERS WITH OPEN TRANSACTIONS ─────────────────────
    inactive_with_open = db.session.query(func.count(Transaction.id)).join(
        Customer, Customer.id == Transaction.customer_id
    ).filter(
        Customer.is_active == False,
        Transaction.status == 'Open'
    ).scalar() or 0

    if inactive_with_open > 0:
        notifications.append({
            "id": "inactive_open_txn",
            "type": "warning",
            "icon": "person_off",
            "title": f"{inactive_with_open} Open Transaction{'s' if inactive_with_open > 1 else ''} — Inactive Customer{'s' if inactive_with_open > 1 else ''}",
            "message": "Deactivated customers still have open transactions.",
            "link": "/admin/customers?filter=inactive_open"
        })

    return notifications

@admin_bp.route('/notifications/stream')
@login_required
@admin_or_staff_required
@limiter.exempt
def notification_stream():
    """Server-Sent Events endpoint — pushes notification data every 30s."""
 
    def generate():
        # Tell the browser to wait 15s before auto-reconnecting if this
        # connection drops (default is ~3s), so a flaky connection doesn't
        # hammer the server with rapid reconnect attempts.
        yield "retry: 15000\n\n"

        notifications = _build_notifications()
        payload = json.dumps({"count": len(notifications), "notifications": notifications})
        yield f"data: {payload}\n\n"
 
        import time
        interval = 30
        elapsed = 0
        while True:
            time.sleep(1)
            elapsed += 1
            if elapsed >= interval:
                elapsed = 0
                notifications = _build_notifications()
                payload = json.dumps({"count": len(notifications), "notifications": notifications})
                yield f"data: {payload}\n\n"
 
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
 
 
@admin_bp.route('/notifications/data')
@login_required
@admin_or_staff_required
@limiter.exempt
def notification_data():
    """One-shot JSON endpoint — used for the initial page load."""
    try:
        notifications = _build_notifications()
        return jsonify({"count": len(notifications), "notifications": notifications})
    except Exception as e:
        current_app.logger.error(f"Notification data error: {e}")
        return jsonify({"count": 0, "notifications": []})
 

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_or_staff_required
def settings():
    """Owner/Admin configuration of business rules (Maintainability NFR, Ch. III)."""
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)

    if request.method == 'POST':
        try:
            deposit_flat = Decimal(request.form.get('deposit_flat_amount', '1500'))
            late_fee = Decimal(request.form.get('late_fee_per_day', '100'))
            minor_pct = int(request.form.get('damage_fee_minor_pct', '25'))
            major_pct = int(request.form.get('damage_fee_major_pct', '50'))
            default_reorder = int(request.form.get('default_reorder_level', '5'))

            if deposit_flat < 0 or late_fee < 0 or default_reorder < 0:
                raise ValueError("Amounts and thresholds cannot be negative.")
            if not (0 <= minor_pct <= 100) or not (0 <= major_pct <= 100):
                raise ValueError("Damage percentages must be between 0 and 100.")
            if minor_pct > major_pct:
                raise ValueError("Minor damage percentage cannot exceed major damage percentage.")

            deposit_tiers = parse_deposit_tiers(
                request.form.get('deposit_distance_tiers', '')
            )
            if not deposit_tiers:
                raise ValueError(
                    "Add at least one distance tier (for example 3:500, 6:1000, *:1500)."
                )
        except (ValueError, InvalidOperation, TypeError) as exc:
            flash(f"Please check the values: {exc}", "danger")
            return redirect(url_for('admin.settings'))

        SystemSetting.set_value(
            'deposit_flat_amount', f"{deposit_flat:.2f}", current_user.id
        )
        SystemSetting.set_value(
            'deposit_distance_tiers',
            format_deposit_tiers(deposit_tiers),
            current_user.id,
        )
        SystemSetting.set_value(
            'late_fee_per_day', f"{late_fee:.2f}", current_user.id
        )
        SystemSetting.set_value('damage_fee_minor_pct', minor_pct, current_user.id)
        SystemSetting.set_value('damage_fee_major_pct', major_pct, current_user.id)
        SystemSetting.set_value(
            'default_reorder_level', default_reorder, current_user.id
        )
        db.session.commit()
        flash("Business rules updated. New transactions will use these values.", "success")
        return redirect(url_for('admin.settings'))

    return render_template(
        "admin/settings.html",
        settings=SystemSetting.all_effective(),
    )


@admin_bp.route('/void-requests')
@login_required
def void_requests():
    """Admin approval queue for staff void/cancel requests (Table 15)."""
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)
    pending = (
        VoidRequest.query.filter_by(status='Pending')
        .order_by(VoidRequest.requested_at.asc())
        .all()
    )
    history = (
        VoidRequest.query.filter(VoidRequest.status != 'Pending')
        .order_by(VoidRequest.reviewed_at.desc(), VoidRequest.requested_at.desc())
        .limit(25)
        .all()
    )
    return render_template(
        'admin/void_requests.html', pending=pending, history=history
    )


@admin_bp.route('/void-requests/<int:request_id>/approve', methods=['POST'])
@login_required
def approve_void_request(request_id):
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)
    req = VoidRequest.query.get_or_404(request_id)
    if req.status != 'Pending':
        flash("This request has already been reviewed.", "info")
        return redirect(url_for('admin.void_requests'))

    if req.transaction.status == 'Cancelled':
        req.status = 'Approved'
        req.reviewed_by_id = current_user.id
        req.reviewed_at = datetime.utcnow()
        req.review_note = (request.form.get('review_note', '').strip()[:255]
                           or "Transaction was already cancelled.")
        db.session.commit()
        flash("Transaction was already cancelled; request closed without another stock adjustment.", "info")
        return redirect(url_for('admin.void_requests'))

    _apply_transaction_cancellation(req.transaction, req.reason, current_user)
    req.status = 'Approved'
    req.reviewed_by_id = current_user.id
    req.reviewed_at = datetime.utcnow()
    req.review_note = request.form.get('review_note', '').strip()[:255]
    db.session.commit()
    flash(f"Void approved for {req.transaction.reference_no}; inventory restored.", "success")
    return redirect(url_for('admin.void_requests'))


@admin_bp.route('/void-requests/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_void_request(request_id):
    if (current_user.role or '').strip() != 'Administrator':
        abort(403)
    req = VoidRequest.query.get_or_404(request_id)
    if req.status != 'Pending':
        flash("This request has already been reviewed.", "info")
        return redirect(url_for('admin.void_requests'))

    req.status = 'Rejected'
    req.reviewed_by_id = current_user.id
    req.reviewed_at = datetime.utcnow()
    req.review_note = request.form.get('review_note', '').strip()[:255]
    db.session.commit()
    flash(f"Void request for {req.transaction.reference_no} rejected.", "info")
    return redirect(url_for('admin.void_requests'))


@admin_bp.route('/staff-management', methods=['GET', 'POST'])
@login_required
def staff_management():
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    staff_members = User.query.filter(User.role.in_(['Staff', 'Administrator']))\
                              .options(joinedload(User.permissions))\
                              .all()

    total_staff_count = len(staff_members)
    admin_count = sum(1 for u in staff_members if u.role == 'Administrator')
    active_staff_count = sum(1 for u in staff_members if u.is_active)

    return render_template(
        'admin/staff_management.html',
        staff_members=staff_members,
        total_staff_count=total_staff_count,
        admin_count=admin_count,
        active_staff_count=active_staff_count,
        positions=list(ROLE_PRESETS.keys())
    )


from extensions import db, passhasher

@admin_bp.route("/staff/create", methods=["POST"])
@login_required
def create_system_user():
    if current_user.role.strip() != 'Administrator':
        return jsonify({"success": False, "message": "Unauthorized."}), 403
    
    data = {
        "email": request.form.get("email", "").strip().lower(),
        "first": request.form.get("first_name", "").strip().title(),
        "last": request.form.get("last_name", "").strip().title(),
        "pwd": request.form.get("password", ""),
    }
    position = (request.form.get("staff_position") or "Counter Staff").strip()
    if position not in ROLE_PRESETS:
        position = "Counter Staff"
    role = ROLE_PRESETS[position]["role"]

    if not all(data.values()):
        flash("All fields are mandatory.", "danger")
        return redirect(url_for("admin.staff_management"))

    pwd_errors = []
    if len(data['pwd']) < 12: pwd_errors.append("12+ characters")
    if not any(c.isupper() for c in data['pwd']): pwd_errors.append("uppercase letter")
    if not any(c.isdigit() for c in data['pwd']): pwd_errors.append("number")
    if not any(c in "!@#$%^&*()-_=+" for c in data['pwd']): pwd_errors.append("special character")

    if pwd_errors:
        return jsonify({"success": False, "message": f"Password weak. Requires: {', '.join(pwd_errors)}"}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({"success": False, "message": "Email already exists in the system."}), 400

    try:
        user_record = User(
            email=data['email'],
            password_hash=passhasher.hash(data['pwd']),
            first_name=data['first'],
            last_name=data['last'],
            role=role,
            staff_position=position,
            is_active=True,
            is_verified=True
        )
        
        db.session.add(user_record)
        db.session.flush() 


        preset = {
            key: value
            for key, value in ROLE_PRESETS[position].items()
            if key != "role"
        }
        new_permissions = Permission(user_id=user_record.id, **preset)
        db.session.add(new_permissions)

        db.session.commit()

        return jsonify({"success": True, "message": f"New system user {data['first']} initialized successfully."})
        
    except Exception as error:
        db.session.rollback()
        current_app.logger.critical(f"Provisioning Failure: {error}")
        return jsonify({"success": False, "message": "System error during record creation. Contact development team."}), 500
    
@admin_bp.route("/update-user-access", methods=["POST"])
@login_required
def update_user_access():
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    user_id = request.form.get("user_id")
    

    user = User.query.get_or_404(user_id)

    user.role = request.form.get("role")
    position = request.form.get("staff_position")
    if position in ROLE_PRESETS:
        user.staff_position = position
        if position == "Owner/Admin":
            user.role = "Administrator"

    perms = Permission.query.filter_by(user_id=user_id).first()
    if not perms:
        perms = Permission(user_id=user_id)
        db.session.add(perms)
    

    perms.can_manage_customers = 'can_manage_customers' in request.form
    perms.can_verify_customers = 'can_verify_customers' in request.form
    perms.can_manage_products = 'can_manage_products' in request.form
    perms.can_update_stock = 'can_update_stock' in request.form
    perms.can_process_transactions = 'can_process_transactions' in request.form
    perms.can_confirm_payments = 'can_confirm_payments' in request.form
    perms.can_export_transactions = 'can_export_transactions' in request.form
    perms.can_manage_expenses = 'can_manage_expenses' in request.form
    perms.can_view_reports = 'can_view_reports' in request.form
    perms.can_view_logs = 'can_view_logs' in request.form
    perms.can_view_active_rentals = 'can_view_active_rentals' in request.form
    
    try:
        db.session.commit()
        flash(f"Access rights and role updated for {user.full_name}.", "success")
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while updating permissions.", "error")
        
    return redirect(url_for('admin.staff_management'))

@admin_bp.route("/delete-user/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    if current_user.role.strip() != 'Administrator':
        flash("Access restricted to Administrators only.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    user = User.query.get_or_404(user_id)

    # Prevent self-deletion
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('admin.staff_management'))

    try:
        # Delete associated permissions first to avoid FK constraint errors
        Permission.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        flash(f"{user.first_name} {user.last_name} has been removed from the system.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"DELETE_USER_ERROR: {e}")
        flash("Failed to delete user. They may have linked records.", "danger")

    return redirect(url_for('admin.staff_management'))