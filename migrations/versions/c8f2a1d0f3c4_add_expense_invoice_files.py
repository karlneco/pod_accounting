"""Add expense invoice files

Revision ID: c8f2a1d0f3c4
Revises: 72b5548a8dee
Create Date: 2026-01-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8f2a1d0f3c4'
down_revision = '72b5548a8dee'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'expense_invoice_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('expense_invoice_id', sa.Integer(), sa.ForeignKey('expense_invoices.id'), nullable=False),
        sa.Column('stored_filename', sa.String(length=256), nullable=False),
        sa.Column('original_filename', sa.String(length=256), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('expense_invoice_files')
