from app import app
from extensions import db, passhasher
from models.users import User

users_to_create = [
    {"email": "caremed.admin@gmail.com",     "password": "Admin@12345",     "role": "Administrator", "first_name": "Admin",     "last_name": "CareMed"},
    {"email": "caremed.staff@gmail.com",     "password": "Staff@12345",     "role": "Staff",         "first_name": "Staff",     "last_name": "CareMed"},
    {"email": "caremed.custodian@gmail.com", "password": "Custodian@12345", "role": "Custodian",     "first_name": "Custodian", "last_name": "CareMed"},
]

with app.app_context():
    for u in users_to_create:
        existing = User.query.filter_by(email=u["email"]).first()
        if existing:
            print("Already exists:", u["email"])
            continue
        user = User(
            email=u["email"],
            password_hash=passhasher.hash(u["password"]),
            role=u["role"],
            first_name=u["first_name"],
            last_name=u["last_name"],
            is_verified=True,
            is_active=True,
        )
        db.session.add(user)
        print("Created:", u["email"], "-", u["role"])
    db.session.commit()
    print("Done.")
