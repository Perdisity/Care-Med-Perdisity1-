"""Distance deposit support, damage approval fields and audit archiving

Revision ID: b8d2f4a1c6e3
Revises: a7c1e9f0b2d4
Create Date: 2026-10-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d2f4a1c6e3'
down_revision = 'a7c1e9f0b2d4'
branch_labels = None
depends_on = None


def upgrade():
    # RULE-10 / TC-11: reason code and Administrator approval snapshot.
    with op.batch_alter_table('rental', schema=None) as batch_op:
        batch_op.add_column(sa.Column('damage_reason', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('damage_approved_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('damage_approved_at', sa.DateTime(), nullable=True))

    # NFR (permanent audit log): archive rather than hard-delete.
    with op.batch_alter_table('security_logs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_archived',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0'),
            )
        )
        batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('archived_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('archive_reason', sa.String(length=255), nullable=True))
        batch_op.create_index('ix_security_logs_is_archived', ['is_archived'])


def downgrade():
    with op.batch_alter_table('security_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_security_logs_is_archived')
        batch_op.drop_column('archive_reason')
        batch_op.drop_column('archived_by')
        batch_op.drop_column('archived_at')
        batch_op.drop_column('is_archived')

    with op.batch_alter_table('rental', schema=None) as batch_op:
        batch_op.drop_column('damage_approved_at')
        batch_op.drop_column('damage_approved_by_id')
        batch_op.drop_column('damage_reason')
