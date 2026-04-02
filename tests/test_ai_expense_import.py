import io
import json
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import requests

from app import create_app
from app.models import (
    db,
    Account,
    AIExpenseDocument,
    Currency,
    ExpenseInvoice,
    ExpenseInvoiceFile,
    ExpenseItem,
    Provider,
)
from app.services.ai_expense_import import (
    build_supplier_catalog,
    import_document_to_expense,
    process_document,
    rerun_document,
    sync_provider_aliases,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.payload.get('error', 'request failed'))


class AIExpenseImportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, 'test.db')
        self.expense_upload_dir = os.path.join(self.tempdir.name, 'expense_invoices')
        self.ai_upload_dir = os.path.join(self.tempdir.name, 'ai_expense_imports')

        config_class = type('TestConfig', (), {
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.db_path}',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'EXPENSE_INVOICE_UPLOAD_DIR': self.expense_upload_dir,
            'AI_EXPENSE_IMPORT_UPLOAD_DIR': self.ai_upload_dir,
            'IMPORT_UPLOAD_DIR': os.path.join(self.tempdir.name, 'uploads'),
            'OPENAI_API_KEY': 'test-key',
        })
        self.app = create_app(config_class)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

        cad = Currency(code='CAD', name='Canadian Dollar')
        usd = Currency(code='USD', name='US Dollar')
        self.default_account = Account(name='Office Expense', type='Expense')
        self.gst_account = Account(name='GST Paid', type='Expense')
        db.session.add_all([cad, usd, self.default_account, self.gst_account])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tempdir.cleanup()

    def create_provider(self, name='Shopify', currency_code='CAD', aliases=None, with_default_account=True):
        provider = Provider(
            name=name,
            type='software',
            currency_code=currency_code,
            default_account_id=self.default_account.id if with_default_account else None,
        )
        db.session.add(provider)
        db.session.flush()
        sync_provider_aliases(provider, '\n'.join(aliases or []))
        db.session.commit()
        return provider

    def queue_pdf(self, provider_hint_id=None, filename='receipt.pdf', content=b'%PDF-1.4 test'):
        response = self.client.post(
            '/expenses/import/ai',
            data={
                'provider_hint_id': str(provider_hint_id or ''),
                'files': (io.BytesIO(content), filename),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        document = AIExpenseDocument.query.order_by(AIExpenseDocument.id.desc()).first()
        self.assertIsNotNone(document)
        return document

    def mock_openai_success(self, matched_provider_id, supplier_invoice='SUP-1', currency_code='CAD'):
        payload = {
            'matched_provider_id': matched_provider_id,
            'raw_supplier_name': 'Shopify Billing',
            'invoice_date': '2026-04-01',
            'invoice_number': 'INV-100',
            'supplier_invoice': supplier_invoice,
            'currency_code': currency_code,
            'subtotal_amount': '10.00',
            'tax_amount': '0.50',
            'total_amount': '10.50',
            'provider_uncertain': False,
            'line_items_incomplete': False,
            'totals_mismatch': False,
            'possible_duplicate': False,
            'line_items': [
                {'description': 'Subscription', 'amount': '10.00', 'is_tax': False},
                {'description': 'GST', 'amount': '0.50', 'is_tax': True},
            ],
        }

        def fake_post(url, **kwargs):
            if url.endswith('/files'):
                return FakeResponse({'id': 'file-test'})
            if url.endswith('/responses'):
                return FakeResponse({'output_text': json.dumps(payload)})
            raise AssertionError(f'Unexpected URL: {url}')

        return fake_post

    def test_build_supplier_catalog_includes_aliases(self):
        provider = self.create_provider(aliases=['Shopify Billing', 'Shopify Payments'])
        catalog = build_supplier_catalog()

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]['provider_id'], provider.id)
        self.assertEqual(catalog[0]['aliases'], ['Shopify Billing', 'Shopify Payments'])

    def test_pdf_upload_creates_queued_documents(self):
        provider = self.create_provider()

        response = self.client.post(
            '/expenses/import/ai',
            data={
                'provider_hint_id': str(provider.id),
                'files': [
                    (io.BytesIO(b'%PDF-1.4 first'), 'first.pdf'),
                    (io.BytesIO(b'%PDF-1.4 second'), 'second.pdf'),
                ],
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 302)
        documents = AIExpenseDocument.query.order_by(AIExpenseDocument.id.asc()).all()
        self.assertEqual(len(documents), 2)
        self.assertTrue(all(document.status == 'queued' for document in documents))
        self.assertTrue(os.path.exists(os.path.join(self.ai_upload_dir, str(documents[0].batch_id), documents[0].stored_filename)))

    def test_process_document_moves_to_review_with_items(self):
        provider = self.create_provider(aliases=['Shopify Billing'])
        document = self.queue_pdf(provider_hint_id=provider.id)

        with patch('app.services.ai_expense_import.requests.post', side_effect=self.mock_openai_success(provider.id)):
            result = process_document(document.id)

        self.assertTrue(result)
        document = AIExpenseDocument.query.get(document.id)
        self.assertEqual(document.status, 'needs_review')
        self.assertEqual(document.matched_provider_id, provider.id)
        self.assertEqual(document.total_amount, Decimal('10.50'))
        self.assertEqual(len(document.items), 2)

    def test_failed_extraction_stores_error_and_can_rerun(self):
        provider = self.create_provider()
        document = self.queue_pdf(provider_hint_id=provider.id)

        def failing_post(url, **kwargs):
            if url.endswith('/files'):
                return FakeResponse({'id': 'file-test'})
            return FakeResponse({'error': 'model failure'}, status_code=500)

        with patch('app.services.ai_expense_import.requests.post', side_effect=failing_post):
            result = process_document(document.id)

        self.assertFalse(result)
        document = AIExpenseDocument.query.get(document.id)
        self.assertEqual(document.status, 'failed')
        self.assertIn('model failure', document.last_error)

        rerun_document(document)
        document = AIExpenseDocument.query.get(document.id)
        self.assertEqual(document.status, 'queued')

    def test_duplicate_detection_blocks_import(self):
        provider = self.create_provider()
        existing = ExpenseInvoice(
            provider_id=provider.id,
            invoice_date=date(2026, 4, 1),
            invoice_number='OLD-1',
            supplier_invoice='SUP-1',
            total_amount=Decimal('10.50'),
        )
        db.session.add(existing)
        db.session.commit()

        document = self.queue_pdf(provider_hint_id=provider.id)
        with patch('app.services.ai_expense_import.requests.post', side_effect=self.mock_openai_success(provider.id, supplier_invoice='SUP-1')):
            process_document(document.id)

        document = AIExpenseDocument.query.get(document.id)
        self.assertTrue(document.possible_duplicate)
        self.assertEqual(document.duplicate_expense_invoice_id, existing.id)
        with self.assertRaises(ValueError):
            import_document_to_expense(document)

    def test_review_save_and_import_creates_expense_and_attaches_pdf(self):
        provider = self.create_provider()
        document = self.queue_pdf(provider_hint_id=provider.id)

        save_response = self.client.post(
            f'/expenses/review-bucket/{document.id}/save',
            data={
                'matched_provider_id': str(provider.id),
                'raw_supplier_name': 'Shopify Billing',
                'invoice_date': '2026-04-01',
                'invoice_number': 'INV-201',
                'supplier_invoice': 'SUP-201',
                'currency_code': 'CAD',
                'subtotal_amount': '20.00',
                'tax_amount': '1.00',
                'total_amount': '21.00',
                'items-0-description': 'Subscription',
                'items-0-amount': '20.00',
                'items-1-description': 'GST',
                'items-1-amount': '1.00',
                'items-1-is_tax': 'on',
            },
            follow_redirects=False,
        )
        self.assertEqual(save_response.status_code, 302)

        import_response = self.client.post(
            f'/expenses/review-bucket/{document.id}/import',
            follow_redirects=False,
        )
        self.assertEqual(import_response.status_code, 302)

        document = AIExpenseDocument.query.get(document.id)
        invoice = ExpenseInvoice.query.filter_by(invoice_number='INV-201').first()
        self.assertIsNotNone(invoice)
        self.assertEqual(document.status, 'imported')
        self.assertEqual(document.imported_expense_invoice_id, invoice.id)
        self.assertEqual(ExpenseItem.query.filter_by(expense_invoice_id=invoice.id).count(), 2)
        self.assertEqual(ExpenseInvoiceFile.query.filter_by(expense_invoice_id=invoice.id).count(), 1)


if __name__ == '__main__':
    unittest.main()
