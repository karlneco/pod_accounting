"""Add AI expense import queue

Revision ID: e3c4f3b8a9c1
Revises: c8f2a1d0f3c4, a26961c60870
Create Date: 2026-04-01 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3c4f3b8a9c1'
down_revision = ('c8f2a1d0f3c4', 'a26961c60870')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'provider_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(length=128), nullable=False),
        sa.Column('normalized_alias', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_id', 'normalized_alias', name='uq_provider_aliases_provider_id_normalized_alias'),
    )
    op.create_index('ix_provider_aliases_normalized_alias', 'provider_aliases', ['normalized_alias'], unique=False)

    op.create_table(
        'ai_import_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(length=64), nullable=False),
        sa.Column('auto_import_confident', sa.Boolean(), nullable=False),
        sa.Column('max_retry_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'ai_expense_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider_hint_id', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['provider_hint_id'], ['providers.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'ai_expense_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('queued', 'processing', 'needs_review', 'failed', 'imported', 'ignored', name='ai_expense_document_statuses'), nullable=False),
        sa.Column('original_filename', sa.String(length=256), nullable=False),
        sa.Column('stored_filename', sa.String(length=256), nullable=False),
        sa.Column('provider_hint_id', sa.Integer(), nullable=True),
        sa.Column('matched_provider_id', sa.Integer(), nullable=True),
        sa.Column('duplicate_expense_invoice_id', sa.Integer(), nullable=True),
        sa.Column('imported_expense_invoice_id', sa.Integer(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('raw_supplier_name', sa.String(length=256), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('invoice_number', sa.String(length=64), nullable=True),
        sa.Column('supplier_invoice', sa.String(length=64), nullable=True),
        sa.Column('currency_code', sa.String(length=3), nullable=True),
        sa.Column('subtotal_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('provider_uncertain', sa.Boolean(), nullable=False),
        sa.Column('line_items_incomplete', sa.Boolean(), nullable=False),
        sa.Column('totals_mismatch', sa.Boolean(), nullable=False),
        sa.Column('possible_duplicate', sa.Boolean(), nullable=False),
        sa.Column('raw_response_json', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['ai_expense_batches.id']),
        sa.ForeignKeyConstraint(['duplicate_expense_invoice_id'], ['expense_invoices.id']),
        sa.ForeignKeyConstraint(['imported_expense_invoice_id'], ['expense_invoices.id']),
        sa.ForeignKeyConstraint(['matched_provider_id'], ['providers.id']),
        sa.ForeignKeyConstraint(['provider_hint_id'], ['providers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_expense_documents_status', 'ai_expense_documents', ['status'], unique=False)
    op.create_index('ix_ai_expense_documents_batch_id', 'ai_expense_documents', ['batch_id'], unique=False)

    op.create_table(
        'ai_expense_document_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=256), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('is_tax', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['ai_expense_documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ai_expense_document_items')
    op.drop_index('ix_ai_expense_documents_batch_id', table_name='ai_expense_documents')
    op.drop_index('ix_ai_expense_documents_status', table_name='ai_expense_documents')
    op.drop_table('ai_expense_documents')
    op.drop_table('ai_expense_batches')
    op.drop_table('ai_import_settings')
    op.drop_index('ix_provider_aliases_normalized_alias', table_name='provider_aliases')
    op.drop_table('provider_aliases')
