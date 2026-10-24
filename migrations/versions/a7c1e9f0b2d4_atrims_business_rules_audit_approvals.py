"""ATRIMS-CareMed business rules, audit trail and approval queues

Revision ID: a7c1e9f0b2d4
Revises: 84cb0ad52ee2
Create Date: 2026-10-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c1e9f0b2d4'
down_revision = '84cb0ad52ee2'
branch_labels = None
depends_on = None


def upgrade():
    # ── Editable business rules (FR02, RULE-03/09/10, FR07) ─────────────────
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('data_type', sa.String(length=16), nullable=False, server_default='string'),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('key'),
    )

    # ── Per-product reorder level and damaged units ─────────────────────────
    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reorder_level', sa.Integer(), nullable=False, server_default='5'))
        batch_op.add_column(sa.Column('damaged_stock', sa.Integer(), nullable=False, server_default='0'))

    with op.batch_alter_table('tank_status', schema=None) as batch_op:
        batch_op.add_column(sa.Column('damaged_in_stock', sa.Integer(), nullable=False, server_default='0'))

    # ── Delivery distance + deposit rule snapshot ───────────────────────────
    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.add_column(sa.Column('distance_km', sa.Numeric(precision=6, scale=2), nullable=True))
        batch_op.add_column(sa.Column('deposit_rule', sa.String(length=50), nullable=True))

    # ── Transaction-linked movement log (Chapter IV, Table 15) ──────────────
    with op.batch_alter_table('inventory_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transaction_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reference_no', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('reason_code', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('balance_after', sa.Integer(), nullable=True))
        batch_op.create_index('ix_inventory_logs_transaction_id', ['transaction_id'])
        batch_op.create_index('ix_inventory_logs_reference_no', ['reference_no'])
        batch_op.create_index('ix_inventory_logs_reason_code', ['reason_code'])
        batch_op.create_foreign_key(
            'fk_inventory_logs_transaction_id', 'transaction',
            ['transaction_id'], ['id'], ondelete='SET NULL',
        )

    # ── Damage assessment on return (RULE-10) ───────────────────────────────
    with op.batch_alter_table('rental', schema=None) as batch_op:
        batch_op.add_column(sa.Column('return_condition', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('damage_fee', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))

    # ── Job function presets ────────────────────────────────────────────────
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('staff_position', sa.String(length=40), nullable=True))

    # ── Supplier batch quantities (FR06) ────────────────────────────────────
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.add_column(sa.Column('refill_quantity', sa.Integer(), nullable=True))

    # ── Void approval queue (Table 15: reason + admin approval) ─────────────
    op.create_table(
        'void_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Pending'),
        sa.Column('requested_by_id', sa.Integer(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['transaction_id'], ['transaction.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Physical count adjustments (RULE-06) ────────────────────────────────
    op.create_table(
        'stock_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('system_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('counted_qty', sa.Integer(), nullable=False),
        sa.Column('variance', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reason_code', sa.String(length=40), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Pending'),
        sa.Column('requested_by_id', sa.Integer(), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('stock_adjustments')
    op.drop_table('void_requests')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('staff_position')

    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.drop_column('refill_quantity')

    with op.batch_alter_table('rental', schema=None) as batch_op:
        batch_op.drop_column('damage_fee')
        batch_op.drop_column('return_condition')

    with op.batch_alter_table('inventory_logs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_inventory_logs_transaction_id', type_='foreignkey')
        batch_op.drop_index('ix_inventory_logs_reason_code')
        batch_op.drop_index('ix_inventory_logs_reference_no')
        batch_op.drop_index('ix_inventory_logs_transaction_id')
        batch_op.drop_column('balance_after')
        batch_op.drop_column('reason_code')
        batch_op.drop_column('reference_no')
        batch_op.drop_column('transaction_id')

    with op.batch_alter_table('transaction', schema=None) as batch_op:
        batch_op.drop_column('deposit_rule')
        batch_op.drop_column('distance_km')

    with op.batch_alter_table('tank_status', schema=None) as batch_op:
        batch_op.drop_column('damaged_in_stock')

    with op.batch_alter_table('product', schema=None) as batch_op:
        batch_op.drop_column('damaged_stock')
        batch_op.drop_column('reorder_level')

    op.drop_table('system_settings')
