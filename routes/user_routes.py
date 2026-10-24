from dateutil.relativedelta import relativedelta
from flask import Blueprint, abort, render_template, request, current_app, jsonify, redirect, url_for, flash, session
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from extensions import db, passhasher, limiter
from forms.update_profile_form import UpdateProfileForm, ChangePasswordForm
from functools import wraps
from models.customer import Customer
from models.product import Product, Cart, CartItem, Payment, Transaction, Rental, Purchase, InventoryLog, PaymentProof, ProductReview
from models.users import User
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import os
import uuid
from PIL import Image
import random
import string
from sqlalchemy import or_

user_bp = Blueprint('user', __name__, url_prefix='/customer')


def customer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        if current_user.role == 'Administrator':
            return redirect(url_for('admin.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def admin_redirect(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.role and current_user.role.strip()== 'Administrator':
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@user_bp.route('/')
@admin_redirect
def homepage():
    all_products = Product.query.all()
    
    rent_only = [p for p in all_products if p.transaction_type == 'Rental' and p.is_active and p.stock > 0]
    sale_only = [p for p in all_products if p.transaction_type == 'Sale' and p.is_active and p.stock > 0]

    featured_products = []
    if rent_only:
        featured_products.append(random.choice(rent_only))
    if sale_only:
        featured_products.append(random.choice(sale_only))

    return render_template('user/homepage.html', products=featured_products)

from sqlalchemy.orm import joinedload
@user_bp.route('/dashboard')
@login_required
def dashboard():
    profile = current_user.customer_profile
    if not profile:
        return redirect(url_for('user.profile'))

    orders = Transaction.query.filter_by(
        customer_id=profile.id,
        transaction_type='Sale'
    ).options(
        joinedload(Transaction.purchases).joinedload(Purchase.product)
    ).order_by(Transaction.created_at.desc()).all()

    rentals = Transaction.query.filter_by(
        customer_id=profile.id,
        transaction_type='Rental'
    ).options(
        joinedload(Transaction.rentals).joinedload(Rental.product)
    ).order_by(Transaction.created_at.desc()).all()


    all_transactions = sorted(orders + rentals, key=lambda x: x.created_at, reverse=True)

    for trans in all_transactions:
        if not trans.tracking_stage:
            trans.tracking_stage = "SUBMITTED"

    return render_template(
        'user/dashboard.html',
        orders=orders,
        rentals=rentals,
        all_transactions=all_transactions
    )

@user_bp.route('/cancel-order/<int:order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    profile = current_user.customer_profile
    if not profile:
        flash("Profile not found.", "danger")
        return redirect(url_for('user.dashboard'))

    order = Transaction.query.filter_by(
        id=order_id,
        customer_id=profile.id,
        transaction_type='Sale'
    ).first()

    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for('user.dashboard'))

    if order.status and order.status.upper() == "CANCELLED":
        flash("Order is already cancelled.", "warning")
        return redirect(url_for('user.dashboard'))

    if order.tracking_status and order.tracking_status.upper() in ['SHIPPING', 'DELIVERED']:
        flash("You can no longer cancel this order.", "danger")
        return redirect(url_for('user.dashboard'))

    if order.payment_status and order.payment_status.lower() == "fully paid":
        flash("Cannot cancel a fully paid order.", "danger")
        return redirect(url_for('user.dashboard'))

    order.status = "CANCELLED"
    order.tracking_status = "CANCELLED"

    try:
        db.session.commit()
        flash("Order cancelled successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Something went wrong while cancelling.", "danger")

    return redirect(url_for('user.dashboard'))

@user_bp.route('/products')
@admin_redirect
def products():
    category = request.args.get('category', 'All')
    search_query = request.args.get('search', '').strip()
    sort_option = request.args.get('sort', 'default')

    query = Product.query

    if category != 'All':
        query = query.filter(Product.equipment_type == category)

    if search_query:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search_query}%'),
                Product.equipment_type.ilike(f'%{search_query}%'),
                Product.description.ilike(f'%{search_query}%')
            )
        )

    if sort_option == 'price-low':
        query = query.order_by(Product.sale_price.asc(), Product.rent_price.asc())
    elif sort_option == 'price-high':
        query = query.order_by(Product.sale_price.desc(), Product.rent_price.desc())

    all_products = query.all()
    
    in_cart_items = []
    if current_user.is_authenticated:
        user_cart = Cart.query.filter_by(user_id=current_user.id).first()
        if user_cart:
            in_cart_items = [(item.product_id, item.item_type) for item in user_cart.items]
            
    return render_template('user/products.html', products=all_products, current_category=category, in_cart_items=in_cart_items)


@user_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.options(
            joinedload(Product.reviews)
            .joinedload(ProductReview.user)
            .joinedload(User.customer_profile)
        ).get_or_404(product_id)
    
    category = request.args.get('category', 'All')
    search_query = request.args.get('search', '').strip()
    sort_option = request.args.get('sort', 'default')

    query = Product.query

    if category != 'All':
        query = query.filter(Product.equipment_type == category)

    if search_query:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search_query}%'),
                Product.equipment_type.ilike(f'%{search_query}%'),
                Product.description.ilike(f'%{search_query}%')
            )
        )

    if sort_option == 'price-low':
        query = query.order_by(Product.sale_price.asc(), Product.rent_price.asc())
    elif sort_option == 'price-high':
        query = query.order_by(Product.sale_price.desc(), Product.rent_price.desc())

    all_products = query.all()
    
    in_cart_items = []
    if current_user.is_authenticated:
        user_cart = Cart.query.filter_by(user_id=current_user.id).first()
        if user_cart:
            in_cart_items = [(item.product_id, item.item_type) for item in user_cart.items]
            
    return render_template('user/product_detail.html', product=product, products=all_products, current_category=category, in_cart_items=in_cart_items)


@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@customer_required
@limiter.limit("10 per minute")
def profile():
    profile_form = UpdateProfileForm()
    password_form = ChangePasswordForm()

    if not current_user.customer_profile:
        current_user.customer_profile = Customer(user_id=current_user.id)
        db.session.add(current_user.customer_profile)
        db.session.commit()

    customer = current_user.customer_profile

    if request.method == "GET":
        profile_form.first_name.data = customer.first_name or None
        profile_form.last_name.data = customer.last_name or None
        profile_form.phone.data = customer.contact_number or None
        profile_form.address.data = customer.home_address or None
        profile_form.primary_id_type.data = customer.primary_id_type or None
        profile_form.secondary_id_type.data = customer.secondary_id_type or None

        return render_template("user/profile.html", profile_form=profile_form, password_form=password_form)

    if profile_form.validate_on_submit() and profile_form.submit_profile.data:
        try:
            customer.first_name = profile_form.first_name.data.strip().title()
            customer.last_name = profile_form.last_name.data.strip().title()
            customer.contact_number = profile_form.phone.data.strip()
            customer.home_address = profile_form.address.data.title()
            
            customer.primary_id_type = profile_form.primary_id_type.data
            customer.secondary_id_type = profile_form.secondary_id_type.data

            remove_photo_signal = request.form.get('remove_photo') == 'true'
            new_profile_file = profile_form.profile_path.data

            if remove_photo_signal and not new_profile_file:
                if current_user.profile_path:
                    old_path = os.path.join(current_app.root_path, 'static', current_user.profile_path)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                    current_user.profile_path = None

            if new_profile_file:
                if current_user.profile_path:
                    old_path = os.path.join(current_app.root_path, 'static', current_user.profile_path)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                filename = secure_filename(f"user_{current_user.id}_{new_profile_file.filename}")
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
                os.makedirs(upload_folder, exist_ok=True)
                new_profile_file.save(os.path.join(upload_folder, filename))
                current_user.profile_path = f"uploads/profiles/{filename}"

            primary_id_file = profile_form.valid_id_path.data
            if primary_id_file:
                if customer.valid_id_path:
                    old_path = os.path.join(current_app.root_path, 'static', customer.valid_id_path)
                    if os.path.exists(old_path): os.remove(old_path)
                
                filename = secure_filename(f"primary_id_{current_user.id}_{primary_id_file.filename}")
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'ids')
                os.makedirs(upload_folder, exist_ok=True)
                primary_id_file.save(os.path.join(upload_folder, filename))
                customer.valid_id_path = f"uploads/ids/{filename}"
                customer.id_uploaded_at = datetime.utcnow()

            secondary_id_file = profile_form.secondary_id_path.data
            if secondary_id_file:
                if customer.secondary_id_path:
                    old_path = os.path.join(current_app.root_path, 'static', customer.secondary_id_path)
                    if os.path.exists(old_path): os.remove(old_path)
                
                filename = secure_filename(f"secondary_id_{current_user.id}_{secondary_id_file.filename}")
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'ids')
                os.makedirs(upload_folder, exist_ok=True)
                secondary_id_file.save(os.path.join(upload_folder, filename))
                customer.secondary_id_path = f"uploads/ids/{filename}"
                customer.id_uploaded_at = datetime.utcnow()

            db.session.commit()
            return jsonify(
                status="success",
                message="Your profile and identification documents have been updated successfully!"
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Profile update failed: {e}")
            return jsonify(status="error", message="Oops! We couldn’t update your profile. Please try again.")

    if request.method == "POST":
        error_messages = []
        for field, errors in profile_form.errors.items():
            for error in errors:
                error_messages.append(f"{field.replace('_', ' ').title()}: {error}")

        return jsonify(status="error", message="Please correct the highlighted fields and try again.", errors=error_messages)

    return render_template("user/profile.html", profile_form=profile_form, password_form=password_form)


@user_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if current_user.password_hash:
            try:
                passhasher.verify(current_user.password_hash, form.current_password.data)
            except:
                return jsonify(status="error", errors={"current_password": ["Current password is incorrect."]})

        current_user.password_hash = passhasher.hash(form.new_password.data)

        try:
            db.session.commit()
            return jsonify(status="success", message="Password updated successfully!")
        except:
            db.session.rollback()
            return jsonify(status="error", errors={"new_password": ["An error occurred while updating password."]})

    else:
        errors = {}
        for field, msgs in form.errors.items():
            errors[field] = msgs

        return jsonify(status="error", errors=errors)
    


@user_bp.route('/add-to-cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    if product.stock <= 0:
        flash(f"Sorry, {product.name} is currently out of stock.", "error")
        return redirect(request.referrer or url_for('user.products'))

    item_type = request.form.get('item_type', 'Sale') 
    start_date_str = request.form.get('start_date')
    duration_str = request.form.get('duration')
    next_page = request.form.get('next_page') 

    user_cart = Cart.query.filter_by(user_id=current_user.id).first()
    if not user_cart:
        user_cart = Cart(user_id=current_user.id)
        db.session.add(user_cart)
        db.session.flush() 

    rental_start = None
    rental_duration = None
    
    if item_type == 'Rental':
        try:
            if start_date_str:
                rental_start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            else:
                rental_start = datetime.utcnow().date()
            
            rental_duration = int(duration_str) if duration_str else 1
        except (ValueError, TypeError):
            flash("Invalid date or duration provided.", "error")
            return redirect(request.referrer or url_for('user.products'))

    existing_item = CartItem.query.filter_by(
        cart_id=user_cart.id, 
        product_id=product_id, 
        item_type=item_type,
        rental_start_date=rental_start
    ).first()

    if existing_item:
        if existing_item.quantity + 1 > product.stock:
            flash(f"Cannot add more. Only {product.stock} units available.", "warning")
        else:
            existing_item.quantity += 1
    else:
        price = product.sale_price if item_type == 'Sale' else product.rent_price
        
        new_item = CartItem(
            cart_id=user_cart.id,
            product_id=product_id,
            item_type=item_type,
            price_at_addition=price or 0,
            rental_start_date=rental_start,
            rental_duration=rental_duration,
            quantity=1
        )
        db.session.add(new_item)

    try:
        db.session.commit()
        
        if next_page == 'cart':
            return redirect(url_for('user.cart', added_id=product_id, added_type=item_type))
            
        flash(f"Added {product.name} to cart.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while updating your cart.", "error")

    return redirect(request.referrer or url_for('user.products'))

@user_bp.route('/update_rental/<int:item_id>', methods=['POST'])
@login_required
def update_rental(item_id):
    item = CartItem.query.get_or_404(item_id)
    
    if item.cart.user_id != current_user.id:
        current_app.logger.warning(f"Unauthorized update attempt by user {current_user.id} on item {item_id}")
        return abort(403)
        
    start_date_str = request.form.get('start_date')
    duration_str = request.form.get('duration')
    
    if not start_date_str or not duration_str:
        flash("Missing required rental information.", "warning")
        return redirect(url_for('user.cart'))

    try:
        item.rental_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        item.rental_duration = int(duration_str)
        
        db.session.commit()
        flash("Rental schedule updated successfully!", "success")
    except (ValueError, TypeError) as e:
        db.session.rollback()
        current_app.logger.error(f"Update failed: {str(e)}")
        flash("Invalid date or duration provided.", "danger")
    
    return redirect(url_for('user.cart'))


@user_bp.route('/remove-from-cart/<int:product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    item_type = request.form.get('item_type')
    user_cart = Cart.query.filter_by(user_id=current_user.id).first()
    
    if user_cart:
        item_to_remove = CartItem.query.filter_by(
            cart_id=user_cart.id, 
            product_id=product_id, 
            item_type=item_type
        ).first()
        
        if item_to_remove:
            db.session.delete(item_to_remove)
            db.session.commit()
            flash(f"Removed {item_type} from cart.", "info")
        else:
            flash("Item not found in cart.", "warning")
            
    return redirect(request.referrer or url_for('user.products'))


@user_bp.route('/cart')
@login_required
def cart():
    user_cart = Cart.query.filter_by(user_id=current_user.id).first()
    items = user_cart.items if user_cart else []
    
    rentals = [i for i in items if i.item_type == 'Rental']
    purchases = [i for i in items if i.item_type == 'Sale']

    return render_template(
        'user/user_cart.html', 
        rentals=rentals, 
        purchases=purchases,
        has_items=len(items) > 0
    )
    
@user_bp.route('/cart/action', methods=['POST'])
@login_required
def cart_actions():
    action = request.form.get('action')
    single_delete_val = request.form.get('single_delete')
    selected_items = request.form.getlist('selected_items')
    
    user_cart = Cart.query.filter_by(user_id=current_user.id).first()
    if not user_cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for('user.cart'))

    # 1. Handle quantity updates from auto-submitted inputs
    quantity_updated = False
    for key, value in request.form.items():
        if key.startswith('quantity_'):
            try:
                parts = key.split('_')
                p_id = int(parts[1])
                i_type = parts[2]
                new_qty = int(value)

                cart_item = CartItem.query.filter_by(
                    cart_id=user_cart.id,
                    product_id=p_id,
                    item_type=i_type
                ).first()

                if cart_item and new_qty > 0:
                    if new_qty <= cart_item.product.stock:
                        cart_item.quantity = new_qty
                        quantity_updated = True
            except Exception:
                continue

    if quantity_updated:
        db.session.commit()

    to_delete = []

    if single_delete_val:
        to_delete.append(single_delete_val)
    elif action == 'delete_selected':
        if not selected_items:
            flash("No items selected to delete.", "warning")
            return redirect(url_for('user.cart'))
        to_delete = selected_items

    elif action == 'checkout':
        if not selected_items:
            flash("Please select at least one item to proceed to checkout.", "warning")
            return redirect(url_for('user.cart'))
        
        session['checkout_items'] = selected_items
        return redirect(url_for('user.checkout'))

    if to_delete:
        try:
            for item in to_delete:
                p_id, i_type = item.split(':')
                item_to_remove = CartItem.query.filter_by(
                    cart_id=user_cart.id, 
                    product_id=int(p_id), 
                    item_type=i_type
                ).first()
                if item_to_remove:
                    db.session.delete(item_to_remove)
            db.session.commit()
            flash("Updated your cart successfully.", "info")
            return redirect(url_for('user.cart'))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred while updating your cart.", "error")
            return redirect(url_for('user.cart'))

    if quantity_updated and not to_delete:
        flash("Cart quantities updated.", "success")

    return redirect(url_for('user.cart'))


@user_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    user_cart = Cart.query.filter_by(user_id=current_user.id).first()
    if not user_cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for('user.cart'))

    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith('quantity_'):
                try:
                    parts = key.split('_')
                    p_id = int(parts[1])
                    i_type = parts[2]
                    new_qty = int(value)

                    cart_item = CartItem.query.filter_by(
                        cart_id=user_cart.id,
                        product_id=p_id,
                        item_type=i_type
                    ).first()

                    if cart_item and new_qty > 0:
                        if new_qty <= cart_item.product.stock:
                            cart_item.quantity = new_qty
                except Exception:
                    continue
        
        db.session.commit()
        flash("Cart quantities updated.", "success")
        return redirect(url_for('user.checkout'))

    selected_keys = session.get('checkout_items', [])
    
    if not selected_keys:
        flash("No items selected for checkout.", "warning")
        return redirect(url_for('user.cart'))

    items_to_buy = []
    total_price = Decimal('0.00')
    has_rental = False

    for key in selected_keys:
        try:
            p_id, i_type = key.split(':')
            cart_item = CartItem.query.filter_by(
                cart_id=user_cart.id,
                product_id=int(p_id),
                item_type=i_type
            ).first()

            if cart_item:
                items_to_buy.append(cart_item)
                price = Decimal(str(cart_item.price_at_addition or 0))
                total_price += price * cart_item.quantity
                
                if cart_item.item_type == 'Rental':
                    has_rental = True
                    
        except Exception:
            continue

    if not items_to_buy:
        flash("Selected items are no longer in your cart.", "error")
        return redirect(url_for('user.cart'))

    return render_template('user/check_out.html', 
                           items=items_to_buy, 
                           total_price=total_price,
                           has_rental=has_rental)
    

@user_bp.route('/checkout/update-profile', methods=['POST'])
@login_required
def update_checkout_profile():
    profile = current_user.customer_profile
    
    if not profile:
        flash("Customer profile not found. Please complete your profile first.", "error")
        return redirect(url_for('user.checkout'))
    
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    contact_number = request.form.get('contact_number')
    home_address = request.form.get('home_address')

    try:
        profile.first_name = first_name
        profile.last_name = last_name
        profile.contact_number = contact_number
        profile.home_address = home_address.title()

        db.session.commit()
        flash("Delivery details updated successfully!", "success")
        
    except Exception as e:
        db.session.rollback()
        flash("An error occurred while updating your details. Please try again.", "error")

    return redirect(url_for('user.checkout'))
    

@user_bp.route('/place-order', methods=['POST'])
@login_required
def place_order():
    profile = current_user.customer_profile

    if not profile or not profile.home_address:
        flash("Please provide a delivery address before proceeding.", "info")
        return redirect(url_for('user.checkout'))

    selected_item_ids = request.form.getlist('selected_items')
    if not selected_item_ids:
        flash("Please select at least one item to order.", "warning")
        return redirect(url_for('user.cart'))

    cart = Cart.query.filter_by(user_id=current_user.id).first()
    if not cart or not cart.items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for('user.cart'))


    target_items = [item for item in cart.items if str(item.id) in selected_item_ids]

    is_rental_order = any(item.item_type == 'Rental' for item in target_items)
    
    if is_rental_order:
        if not profile.valid_id_path or not profile.secondary_id_path:
            flash("Rental orders require two forms of valid ID for verification.", "error")
            return redirect(url_for('user.checkout'))

    payment_method = request.form.get('payment_method', 'COD')

    try:
        now = datetime.now()
        prefix = "RNT" if is_rental_order else "PUR"
        ref_no = f"{prefix}-{now.strftime('%m%d%Y-%H%M%S')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"

        new_transaction = Transaction(
            reference_no=ref_no,
            customer_id=profile.id,
            customer_name=f"{profile.first_name} {profile.last_name}",
            transaction_type='Rental' if is_rental_order else 'Sale',
            total_amount=Decimal("0.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("0.00"),
            payment_method=payment_method,
            payment_status="Pending Proof" if payment_method != 'COD' else "Unpaid",
            status="Open",
            fulfillment_type="Delivery",
            delivery_address=profile.home_address,
            delivery_status="Pending"
        )

        db.session.add(new_transaction)
        db.session.flush()

        total_accumulated = Decimal("0.00")

        for item in target_items:
            product = Product.query.with_for_update().get(item.product_id)
            
            if not product or product.status == 'Archived':
                raise ValueError(f"'{item.product.name}' is no longer available.")
            if product.stock < item.quantity:
                raise ValueError(f"Only {product.stock} units of {product.name} are left.")

            item_price = Decimal(str(item.price_at_addition))
            item_total = item_price * item.quantity
            total_accumulated += item_total

            if item.item_type == 'Sale':
                new_purchase = Purchase(
                    transaction_id=new_transaction.id, 
                    product_id=product.id, 
                    customer_id=profile.id,
                    product_name=product.name,
                    product_type=getattr(product, 'equipment_type', None),
                    product_asset_tag=getattr(product, 'asset_tag', None),
                    product_condition=getattr(product, 'condition', None),
                    product_category=getattr(product, 'category', None),
                    quantity=item.quantity, 
                    unit_price=item_price, 
                    total_price=item_total
                )
                db.session.add(new_purchase)
            else:
                end_date = item.rental_start_date + relativedelta(months=item.rental_duration)
                rental = Rental(transaction_id=new_transaction.id, product_id=product.id, 
                                customer_id=profile.id, start_date=item.rental_start_date, 
                                expected_return_date=end_date, monthly_rate=item_price, 
                                quantity=item.quantity, status="Active")
                db.session.add(rental)
                db.session.flush()
                rental.generate_monthly_invoices()

            # TC-04: conditional decrement keeps the online checkout safe when
            # two customers order the last unit at the same time.
            updated_rows = Product.query.filter(
                Product.id == product.id,
                Product.stock >= item.quantity,
            ).update(
                {Product.stock: Product.stock - item.quantity},
                synchronize_session=False,
            )
            if not updated_rows:
                raise ValueError(f"Only {product.stock} units of {product.name} are left.")
            db.session.refresh(product)
            if product.stock <= 0: product.status = "Out of Stock"

            db.session.add(InventoryLog(
                product_id=product.id,
                transaction_id=new_transaction.id,
                reference_no=ref_no,
                reason_code="ONLINE_ORDER",
                action="Online Order",
                quantity=-item.quantity,
                balance_after=product.stock,
                note=f"Online order {ref_no}",
                user_id=current_user.id,
                user_name=new_transaction.customer_name,
            ))

            db.session.delete(item)

        new_transaction.total_amount = total_accumulated
        new_transaction.update_totals()
        db.session.commit()

        if payment_method == 'COD':
            # flash(f"Order successful! Your reference is {ref_no}.", "success")
            return redirect(url_for('user.order_success', ref=ref_no))
        else:
            return redirect(url_for('user.payment_upload', txn_id=new_transaction.id))

    except ValueError as ve:
        db.session.rollback()
        flash(str(ve), "warning")
        return redirect(url_for('user.cart'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"CHECKOUT_ERROR: {str(e)}")
        flash("Could not process order. Please try again.", "error")
        return redirect(url_for('user.checkout'))
    

@user_bp.route('/payment-upload/<int:txn_id>')
@login_required
def payment_upload(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    return render_template('user/payment_submission.html', txn=txn)

@user_bp.route('/submit-payment-proof/<int:txn_id>', methods=['POST'])
@login_required
def submit_payment_proof(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    profile = current_user.customer_profile

    if not profile or txn.customer_id != profile.id:
        current_app.logger.warning(f"Unauthorized payment upload attempt by User {current_user.id} on TXN {txn_id}")
        flash("Authorization failed. Please access the order through your dashboard.", "error")
        return redirect(url_for('user.index'))

    if txn.payment_status in ["Awaiting Verification", "Paid"]:
        flash("This payment is already being processed. You'll receive an update shortly!", "info")
        return redirect(url_for('user.order_success', ref=txn.reference_no))

    proof_file = request.files.get('payment_screenshot')
    if not proof_file or proof_file.filename == '':
        flash("Please select a screenshot of your payment confirmation to proceed.", "warning")
        return redirect(url_for('user.payment_upload', txn_id=txn.id))

    ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
    ext = os.path.splitext(proof_file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        flash("Invalid file format. Please upload a clear image (JPG, PNG, or WebP).", "error")
        return redirect(url_for('user.payment_upload', txn_id=txn.id))

    try:
        unique_id = uuid.uuid4().hex[:12]
        filename = secure_filename(f"proof_{txn.id}_{unique_id}{ext}")

        upload_path = os.path.join(current_app.static_folder, 'uploads/payments')
        if not os.path.exists(upload_path):
            os.makedirs(upload_path, mode=0o755)

        file_full_path = os.path.join(upload_path, filename)
        proof_file.save(file_full_path)

        try:
            with Image.open(file_full_path) as img:
                img.verify() 

            with Image.open(file_full_path) as img:
                if img.format.lower() not in ['png', 'jpeg', 'webp']:
                    raise ValueError("Invalid image format")

        except Exception:
            os.remove(file_full_path)
            flash("The uploaded file is not a valid or supported image.", "error")
            return redirect(url_for('user.payment_upload', txn_id=txn.id))

        # --- Database transaction ---
        new_payment = Payment(
            transaction_id=txn.id,
            amount=txn.total_amount,
            payment_method=txn.payment_method or 'Electronic Transfer',
            status="Pending",
            reference_number=f"PENDING-{txn.reference_no}"
        )
        db.session.add(new_payment)
        db.session.flush()

        new_proof = PaymentProof(
            transaction_id=txn.id,
            payment_id=new_payment.id,
            reference_number=f"PENDING-{txn.reference_no}",
            proof_image=filename
        )
        db.session.add(new_proof)

        txn.payment_status = "Awaiting Verification"
        db.session.commit()

        flash("Payment proof received! Our team will verify your transaction within 1-2 hours.", "success")
        return redirect(url_for('user.order_success', ref=txn.reference_no))

    except Exception as e:
        db.session.rollback()

        if 'file_full_path' in locals() and os.path.exists(file_full_path):
            os.remove(file_full_path)

        current_app.logger.error(f"CRITICAL_UPLOAD_ERROR (TXN {txn_id}): {str(e)}")
        flash("We encountered a technical issue saving your proof. Please try again or contact support.", "error")
        return redirect(url_for('user.payment_upload', txn_id=txn.id))
    
    
@user_bp.route('/order_success')
@login_required
def order_success():
    ref_no = request.args.get('ref')
    if not ref_no:
        return redirect(url_for('user.homepage'))

    order = Transaction.query.filter_by(
        reference_no=ref_no, 
        customer_id=current_user.customer_profile.id
    ).first()

    if not order:
        flash("Order not found or access denied.", "error")
        return redirect(url_for('user.homepage'))

    items = order.purchases if order.transaction_type == 'Sale' else order.rentals
    

    payment = order.payments[0] if order.payments else None
    payment_method = payment.payment_method if payment else "N/A"

    return render_template(
        'user/order_success.html',
        order=order,
        items=items,
        payment_method=payment_method,
        total_price=order.total_amount
    )
    
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@user_bp.route('/upload-ids', methods=['POST'])
@login_required
@customer_required
@limiter.limit("10 per minute")
def upload_ids():
    try:
        if not current_user.customer_profile:
            current_user.customer_profile = Customer(user_id=current_user.id)
            db.session.add(current_user.customer_profile)
            db.session.commit()

        customer = current_user.customer_profile

        primary_type = request.form.get('primary_id_type')
        secondary_type = request.form.get('secondary_id_type')

        primary_id_file = request.files.get('id_primary')
        secondary_id_file = request.files.get('id_secondary')

        errors = []


        if primary_type and not primary_id_file:
            errors.append("Primary ID type selected but file is missing.")

        if secondary_type and not secondary_id_file:
            errors.append("Secondary ID type selected but file is missing.")

        if not primary_type or not secondary_type:
            errors.append("Both ID types are required.")

        if not primary_id_file or not secondary_id_file:
            errors.append("Both ID files are required.")


        if errors:
            flash(" | ".join(errors), "error")
            return redirect(url_for('user.checkout'))


        if not allowed_file(primary_id_file.filename) or not allowed_file(secondary_id_file.filename):
            flash("Only JPG, PNG, JPEG, WEBP files are allowed.", "error")
            return redirect(url_for('user.checkout'))


        primary_id_file.seek(0, os.SEEK_END)
        primary_size = primary_id_file.tell()

        secondary_id_file.seek(0, os.SEEK_END)
        secondary_size = secondary_id_file.tell()

        primary_id_file.seek(0)
        secondary_id_file.seek(0)

        if primary_size > MAX_FILE_SIZE or secondary_size > MAX_FILE_SIZE:
            flash("Each file must not exceed 5MB.", "error")
            return redirect(url_for('user.checkout'))


        customer.primary_id_type = primary_type
        customer.secondary_id_type = secondary_type

        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'ids')
        os.makedirs(upload_folder, exist_ok=True)


        def delete_old(path):
            if path:
                full_path = os.path.join(current_app.root_path, 'static', path)
                if os.path.exists(full_path):
                    os.remove(full_path)

        delete_old(customer.valid_id_path)
        delete_old(customer.secondary_id_path)


        primary_filename = secure_filename(
            f"primary_id_{current_user.id}_{primary_id_file.filename}"
        )

        primary_path = os.path.join(upload_folder, primary_filename)
        primary_id_file.save(primary_path)

        customer.valid_id_path = f"uploads/ids/{primary_filename}"


        secondary_filename = secure_filename(
            f"secondary_id_{current_user.id}_{secondary_id_file.filename}"
        )

        secondary_path = os.path.join(upload_folder, secondary_filename)
        secondary_id_file.save(secondary_path)

        customer.secondary_id_path = f"uploads/ids/{secondary_filename}"

        customer.id_uploaded_at = datetime.utcnow()
        customer.is_id_verified = False 

        db.session.commit()

        flash("Your IDs have been uploaded successfully!", "success")
        return redirect(url_for('user.checkout'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[UPLOAD IDS ERROR]: {e}")
        flash("Upload failed. Please try again.", "error")
        return redirect(url_for('user.checkout'))
    
    
@user_bp.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def submit_review(product_id):
    product = Product.query.get_or_404(product_id)
    
    rating_val = request.form.get('rating')
    comment_text = request.form.get('comment', '').strip()
    
    if not rating_val:
        flash('Please choose a valid star rating value.', 'error')
        return redirect(url_for('user.product_detail', product_id=product_id))
        
    if not comment_text:
        flash('Review details cannot be left completely blank.', 'error')
        return redirect(url_for('user.product_detail', product_id=product_id))
        
    try:
        rating_score = int(rating_val)
        if rating_score < 1 or rating_score > 5:
            raise ValueError
    except ValueError:
        flash('Invalid rating input detected. Please try again.', 'error')
        return redirect(url_for('user.product_detail', product_id=product_id))

    new_review = ProductReview(
        product_id=product.id,
        user_id=current_user.id,
        rating=rating_score,
        comment=comment_text
    )
    
    try:
        db.session.add(new_review)
        db.session.commit()
        flash('Thank you! Your product review has been submitted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An internal error occurred while trying to save your review.', 'error')
        
    return redirect(url_for('user.product_detail', product_id=product_id))

