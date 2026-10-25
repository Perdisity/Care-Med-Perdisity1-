import os
import sys
import shutil
import tempfile
from decimal import Decimal
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app
from extensions import db, passhasher, limiter
from models.customer import Customer
from models.product import Product
from models.users import Permission, User


@pytest.fixture(scope="session")
def app_instance():
    test_dir = tempfile.mkdtemp()
    test_db = os.path.join(test_dir, "pytest_atrims.db")

    flask_app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "MAIL_SUPPRESS_SEND": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{test_db}",
        "SERVER_NAME": "localhost",
    })
    limiter.enabled = False

    with flask_app.app_context():
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()

    shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def client(app_instance):
    return app_instance.test_client()


@pytest.fixture(scope="session")
def seed_data(app_instance):
    with app_instance.app_context():
        admin = User(
            email="test.admin@gmail.com",
            password_hash=passhasher.hash("Admin@12345"),
            first_name="Test",
            last_name="Admin",
            role="Administrator",
            staff_position="Owner/Admin",
            is_active=True,
            is_verified=True,
        )
        db.session.add(admin)
        db.session.flush()

        db.session.add(Permission(
            user_id=admin.id,
            can_manage_customers=True,
            can_verify_customers=True,
            can_manage_products=True,
            can_update_stock=True,
            can_process_transactions=True,
            can_confirm_payments=True,
            can_export_transactions=True,
            can_manage_expenses=True,
            can_view_reports=True,
            can_view_logs=True,
            can_view_active_rentals=True,
        ))

        staff = User(
            email="test.staff@gmail.com",
            password_hash=passhasher.hash("Staff@12345"),
            first_name="Test",
            last_name="Staff",
            role="Staff",
            staff_position="Counter Staff",
            is_active=True,
            is_verified=True,
        )
        db.session.add(staff)
        db.session.flush()

        db.session.add(Permission(
            user_id=staff.id,
            can_manage_customers=True,
            can_verify_customers=True,
            can_process_transactions=True,
            can_confirm_payments=True,
            can_view_active_rentals=True,
        ))

        customer = Customer(
            first_name="Test",
            last_name="Customer",
            contact_number="09170000000",
            home_address="Iloilo City",
            is_active=True,
        )
        db.session.add(customer)

        wheelchair = Product(
            equipment_type="Wheelchair",
            name="Test Wheelchair",
            size="Adult",
            stock=10,
            reorder_level=2,
            cost_price=Decimal("3000.00"),
            rent_price=Decimal("700.00"),
            sale_price=Decimal("4500.00"),
            rent_period="Monthly",
            transaction_type="Both",
            condition="Brand New",
            is_refillable=False,
            status="Available",
        )
        db.session.add(wheelchair)
        db.session.commit()

        return {
            "admin_id": admin.id,
            "staff_id": staff.id,
            "customer_id": customer.id,
            "product_id": wheelchair.id,
        }
