import json
import os
import shutil
import time
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from flask import current_app
from sqlalchemy.exc import OperationalError
from werkzeug.utils import secure_filename

from ..models import (
    db,
    Account,
    AIExpenseBatch,
    AIExpenseDocument,
    AIExpenseDocumentItem,
    AIImportSettings,
    ExpenseInvoice,
    ExpenseInvoiceFile,
    ExpenseItem,
    Provider,
    ProviderAlias,
)


DOCUMENT_STATUSES = ('queued', 'processing', 'needs_review', 'failed', 'imported', 'ignored')


def normalize_provider_alias(value):
    return ' '.join((value or '').strip().lower().split())


def parse_aliases_text(raw_text):
    aliases = []
    seen = set()
    for line in (raw_text or '').splitlines():
        alias = line.strip()
        normalized = normalize_provider_alias(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append((alias, normalized))
    return aliases


def sync_provider_aliases(provider, raw_text):
    desired = parse_aliases_text(raw_text)
    desired_map = {normalized: alias for alias, normalized in desired}
    existing_map = {alias.normalized_alias: alias for alias in provider.aliases}

    for normalized, alias in list(existing_map.items()):
        if normalized not in desired_map:
            db.session.delete(alias)

    for normalized, alias_value in desired_map.items():
        existing = existing_map.get(normalized)
        if existing:
            existing.alias = alias_value
        else:
            db.session.add(ProviderAlias(
                provider_id=provider.id,
                alias=alias_value,
                normalized_alias=normalized,
            ))


def provider_aliases_text(provider):
    return '\n'.join(alias.alias for alias in provider.aliases)


def get_or_create_ai_import_settings():
    settings = db.session.get(AIImportSettings, 1)
    if settings is None:
        settings = AIImportSettings(
            id=1,
            model_name='gpt-4o',
            auto_import_confident=False,
            max_retry_count=3,
        )
        db.session.add(settings)
        db.session.commit()
    elif settings.model_name == 'gpt-4o-mini':
        # The original default was optimistic for PDF inputs; prefer the safer model.
        settings.model_name = 'gpt-4o'
        db.session.commit()
    return settings


def ai_import_upload_root():
    upload_root = current_app.config.get('AI_EXPENSE_IMPORT_UPLOAD_DIR')
    if not upload_root:
        raise RuntimeError('AI_EXPENSE_IMPORT_UPLOAD_DIR is not configured')
    return upload_root


def ai_batch_dir(batch_id):
    return os.path.join(ai_import_upload_root(), str(batch_id))


def ai_document_path(document):
    return os.path.join(ai_batch_dir(document.batch_id), document.stored_filename)


def _cleanup_batch_if_empty(batch_id):
    remaining = AIExpenseDocument.query.filter_by(batch_id=batch_id).count()
    if remaining:
        return
    batch = db.session.get(AIExpenseBatch, batch_id)
    if batch is not None:
        db.session.delete(batch)
        db.session.flush()
    shutil.rmtree(ai_batch_dir(batch_id), ignore_errors=True)


def _invoice_upload_root():
    upload_root = current_app.config.get('EXPENSE_INVOICE_UPLOAD_DIR')
    if not upload_root:
        raise RuntimeError('EXPENSE_INVOICE_UPLOAD_DIR is not configured')
    return upload_root


def _invoice_dir(invoice_id):
    return os.path.join(_invoice_upload_root(), str(invoice_id))


def save_ai_expense_batch(files, provider_hint_id=None):
    batch = AIExpenseBatch(provider_hint_id=provider_hint_id)
    db.session.add(batch)
    db.session.flush()

    batch_dir = ai_batch_dir(batch.id)
    os.makedirs(batch_dir, exist_ok=True)

    documents = []
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        original = secure_filename(uploaded.filename)
        if not original or not original.lower().endswith('.pdf'):
            continue

        stored_name = f'{uuid.uuid4().hex}.pdf'
        uploaded.save(os.path.join(batch_dir, stored_name))
        document = AIExpenseDocument(
            batch_id=batch.id,
            status='queued',
            original_filename=original,
            stored_filename=stored_name,
            provider_hint_id=provider_hint_id,
        )
        db.session.add(document)
        documents.append(document)

    if not documents:
        shutil.rmtree(batch_dir, ignore_errors=True)
        db.session.delete(batch)
        return None, []

    db.session.commit()
    return batch, documents


def build_supplier_catalog():
    catalog = []
    providers = Provider.query.order_by(Provider.name).all()
    for provider in providers:
        aliases = [alias.alias for alias in provider.aliases]
        catalog.append({
            'provider_id': provider.id,
            'name': provider.name,
            'currency_code': provider.currency_code,
            'default_account_id': provider.default_account_id,
            'aliases': aliases,
        })
    return catalog


def extraction_schema():
    return {
        'name': 'expense_invoice_extraction',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'matched_provider_id': {'type': ['integer', 'null']},
                'raw_supplier_name': {'type': ['string', 'null']},
                'invoice_date': {
                    'type': ['string', 'null'],
                    'description': 'The invoice or receipt date in YYYY-MM-DD format. Prefer a date labeled invoice date, receipt date, order date, statement date, billed date, transaction date, or service date. Do not use due date or payment date unless that is the only visible business date on the document.'
                },
                'invoice_number': {'type': ['string', 'null']},
                'supplier_invoice': {'type': ['string', 'null']},
                'currency_code': {'type': ['string', 'null']},
                'subtotal_amount': {'type': ['string', 'null']},
                'tax_amount': {'type': ['string', 'null']},
                'total_amount': {'type': ['string', 'null']},
                'provider_uncertain': {'type': 'boolean'},
                'line_items_incomplete': {'type': 'boolean'},
                'totals_mismatch': {'type': 'boolean'},
                'possible_duplicate': {'type': 'boolean'},
                'line_items': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'description': {'type': 'string'},
                            'amount': {'type': 'string'},
                            'is_tax': {'type': 'boolean'},
                        },
                        'required': ['description', 'amount', 'is_tax'],
                    },
                },
            },
            'required': [
                'matched_provider_id',
                'raw_supplier_name',
                'invoice_date',
                'invoice_number',
                'supplier_invoice',
                'currency_code',
                'subtotal_amount',
                'tax_amount',
                'total_amount',
                'provider_uncertain',
                'line_items_incomplete',
                'totals_mismatch',
                'possible_duplicate',
                'line_items',
            ],
        },
    }


def _openai_headers():
    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    return {
        'Authorization': f'Bearer {api_key}',
    }


def _upload_pdf_to_openai(pdf_path, original_filename):
    with open(pdf_path, 'rb') as handle:
        response = requests.post(
            'https://api.openai.com/v1/files',
            headers=_openai_headers(),
            data={'purpose': 'user_data'},
            files={'file': (original_filename, handle, 'application/pdf')},
            timeout=120,
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f'OpenAI file upload failed: {response.status_code} {response.text}') from exc
    payload = response.json()
    file_id = payload.get('id')
    if not file_id:
        raise RuntimeError('OpenAI file upload did not return an id')
    return file_id


def _response_text_from_payload(payload):
    output_text = payload.get('output_text')
    if output_text:
        return output_text

    for output in payload.get('output', []):
        content = output.get('content', [])
        for item in content:
            if item.get('type') in {'output_text', 'text'} and item.get('text'):
                return item['text']
    raise RuntimeError('OpenAI response did not include output text')


def extract_invoice_with_openai(document, settings):
    schema = extraction_schema()
    pdf_path = ai_document_path(document)
    file_id = _upload_pdf_to_openai(pdf_path, document.original_filename)

    supplier_catalog = build_supplier_catalog()
    provider_hint = None
    if document.provider_hint_id:
        provider = db.session.get(Provider, document.provider_hint_id)
        if provider:
            provider_hint = {'provider_id': provider.id, 'name': provider.name}

    instructions = (
        'Extract a single expense invoice or receipt from the supplied PDF. '
        'Return only the requested structured data. '
        'For invoice_date, actively look for any visible business date on the PDF, including labels such as invoice date, receipt date, order date, statement date, billed date, transaction date, posted date, or service date. '
        'Return the date in YYYY-MM-DD format. '
        'Prefer invoice/receipt/statement/order/service date over due date or payment date. '
        'If the document shows multiple dates, choose the one that best represents when the expense was issued or incurred. '
        'If the only visible date is a due date or payment date, use it rather than leaving invoice_date null. '
        'Use matched_provider_id only if a supplier clearly matches the provided catalog. '
        'Set provider_uncertain true when supplier matching is ambiguous. '
        'Set line_items_incomplete true if the PDF total is visible but one or more line items are unreadable, missing, or summarized. '
        'Set totals_mismatch true if subtotal + tax does not agree with total or line items do not add up. '
        'Set possible_duplicate true only if the document itself suggests it may already be imported; the application will do final duplicate detection. '
        'Treat one PDF as one invoice. If multiple invoices appear, extract the dominant invoice and set line_items_incomplete true.'
    )

    response = requests.post(
        'https://api.openai.com/v1/responses',
        headers={**_openai_headers(), 'Content-Type': 'application/json'},
        json={
            'model': settings.model_name,
            'input': [
                {
                    'role': 'system',
                    'content': [
                        {'type': 'input_text', 'text': instructions},
                    ],
                },
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'input_text',
                            'text': json.dumps(
                                {
                                    'provider_hint': provider_hint,
                                    'supplier_catalog': supplier_catalog,
                                },
                                indent=2,
                            ),
                        },
                        {
                            'type': 'input_file',
                            'file_id': file_id,
                        },
                    ],
                },
            ],
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': schema['name'],
                    'strict': schema['strict'],
                    'schema': schema['schema'],
                }
            },
        },
        timeout=180,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f'OpenAI responses request failed: {response.status_code} {response.text}'
        ) from exc
    payload = response.json()
    text = _response_text_from_payload(payload)
    return json.loads(text), payload


def _to_decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def apply_extraction_result(document, result, raw_payload=None):
    document.matched_provider_id = result.get('matched_provider_id')
    document.raw_supplier_name = (result.get('raw_supplier_name') or '').strip() or None
    document.invoice_date = _to_date(result.get('invoice_date'))
    document.invoice_number = (result.get('invoice_number') or '').strip() or None
    document.supplier_invoice = (result.get('supplier_invoice') or '').strip() or None
    document.currency_code = (result.get('currency_code') or '').strip() or None
    document.subtotal_amount = _to_decimal(result.get('subtotal_amount'))
    document.tax_amount = _to_decimal(result.get('tax_amount'))
    document.total_amount = _to_decimal(result.get('total_amount'))
    document.provider_uncertain = bool(result.get('provider_uncertain'))
    document.line_items_incomplete = bool(result.get('line_items_incomplete'))
    document.totals_mismatch = bool(result.get('totals_mismatch'))
    document.possible_duplicate = bool(result.get('possible_duplicate'))
    document.raw_response_json = json.dumps(raw_payload or result, default=str)
    document.last_error = None

    for item in list(document.items):
        db.session.delete(item)
    db.session.flush()

    for idx, item in enumerate(result.get('line_items', [])):
        description = (item.get('description') or '').strip()
        amount = _to_decimal(item.get('amount'))
        if not description or amount is None:
            document.line_items_incomplete = True
            continue
        db.session.add(AIExpenseDocumentItem(
            document_id=document.id,
            description=description,
            amount=amount,
            is_tax=bool(item.get('is_tax')),
            sort_order=idx,
        ))

    detect_duplicate_invoice(document)
    db.session.flush()


def detect_duplicate_invoice(document):
    document.duplicate_expense_invoice_id = None
    document.possible_duplicate = bool(document.possible_duplicate)

    if not document.matched_provider_id:
        return None

    query = ExpenseInvoice.query.filter_by(provider_id=document.matched_provider_id)
    candidate = None

    if document.supplier_invoice:
        candidate = query.filter_by(supplier_invoice=document.supplier_invoice).first()

    if candidate is None and document.invoice_number:
        candidate = query.filter_by(invoice_number=document.invoice_number).first()

    if candidate is None and document.invoice_date and document.total_amount is not None:
        candidate = query.filter_by(
            invoice_date=document.invoice_date,
            total_amount=document.total_amount,
        ).first()

    if candidate is not None:
        document.possible_duplicate = True
        document.duplicate_expense_invoice_id = candidate.id
    return candidate


def document_blockers(document):
    blockers = []
    provider = document.matched_provider

    if document.status == 'imported':
        blockers.append('Document is already imported.')
    if not provider:
        blockers.append('A matched supplier is required.')
    elif not provider.default_account_id:
        blockers.append('Matched supplier needs a default account before import.')
    if not document.invoice_date:
        blockers.append('Invoice date is required.')
    if document.total_amount is None:
        blockers.append('Invoice total is required.')
    if not document.items:
        blockers.append('At least one line item is required.')
    if document.provider_uncertain:
        blockers.append('Supplier match is still marked uncertain.')
    if document.line_items_incomplete:
        blockers.append('Line items are marked incomplete.')
    if document.totals_mismatch:
        blockers.append('Totals do not reconcile.')
    if document.possible_duplicate:
        blockers.append('Possible duplicate detected.')
    if provider and document.currency_code and provider.currency_code != document.currency_code:
        blockers.append('Supplier currency does not match the extracted invoice currency.')
    gst_account = Account.query.filter_by(name='GST Paid').first()
    if any(item.is_tax for item in document.items) and gst_account is None:
        blockers.append('GST Paid account is required for tax lines.')
    return blockers


def document_ready_for_auto_import(document):
    return not document_blockers(document)


def _copy_document_pdf_to_invoice(document, invoice):
    os.makedirs(_invoice_dir(invoice.id), exist_ok=True)
    stored_name = f'{uuid.uuid4().hex}.pdf'
    shutil.copyfile(ai_document_path(document), os.path.join(_invoice_dir(invoice.id), stored_name))
    db.session.add(ExpenseInvoiceFile(
        expense_invoice_id=invoice.id,
        stored_filename=stored_name,
        original_filename=document.original_filename,
    ))


def import_document_to_expense(document):
    blockers = document_blockers(document)
    if blockers:
        raise ValueError('; '.join(blockers))

    provider = document.matched_provider
    invoice = ExpenseInvoice(
        provider_id=provider.id,
        invoice_date=document.invoice_date,
        invoice_number=document.invoice_number,
        supplier_invoice=document.supplier_invoice,
        total_amount=document.total_amount,
    )
    db.session.add(invoice)
    db.session.flush()

    gst_account = Account.query.filter_by(name='GST Paid').first()
    for item in document.items:
        account_id = gst_account.id if item.is_tax else provider.default_account_id
        db.session.add(ExpenseItem(
            expense_invoice_id=invoice.id,
            account_id=account_id,
            description=item.description,
            amount=item.amount,
            currency_code=provider.currency_code,
            order_id=document.invoice_number,
        ))

    _copy_document_pdf_to_invoice(document, invoice)
    document.status = 'imported'
    document.imported_expense_invoice_id = invoice.id
    document.last_error = None
    db.session.flush()
    return invoice


def process_document(document_id):
    settings = get_or_create_ai_import_settings()
    document = db.session.get(AIExpenseDocument, document_id)
    if document is None:
        return False

    document.status = 'processing'
    document.attempt_count += 1
    document.last_error = None
    db.session.commit()

    try:
        result, raw_payload = extract_invoice_with_openai(document, settings)
        apply_extraction_result(document, result, raw_payload)
        document.status = 'needs_review'

        if settings.auto_import_confident and document_ready_for_auto_import(document):
            import_document_to_expense(document)

        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        document = db.session.get(AIExpenseDocument, document_id)
        if document is None:
            return False
        document.status = 'failed'
        document.last_error = str(exc)
        db.session.commit()
        current_app.logger.exception('AI expense import failed for document %s', document_id)
        return False


def process_next_queued_document():
    try:
        document = (
            AIExpenseDocument.query
            .filter_by(status='queued')
            .order_by(AIExpenseDocument.id.asc())
            .first()
        )
    except OperationalError as exc:
        db.session.rollback()
        if 'no such table: ai_expense_documents' in str(exc):
            current_app.logger.warning('AI expense worker is waiting for database migrations to create ai_expense_documents.')
            return None
        raise
    if document is None:
        return None
    process_document(document.id)
    return document.id


def run_worker_loop(poll_interval=10, once=False):
    while True:
        processed_id = process_next_queued_document()
        if once:
            return processed_id
        if processed_id is None:
            time.sleep(poll_interval)


def rerun_document(document):
    document.status = 'queued'
    document.last_error = None
    document.provider_uncertain = False
    document.line_items_incomplete = False
    document.totals_mismatch = False
    document.possible_duplicate = False
    document.duplicate_expense_invoice_id = None
    document.imported_expense_invoice_id = None
    db.session.commit()


def ignore_document(document):
    document.status = 'ignored'
    db.session.commit()


def delete_document(document):
    if document.status == 'imported':
        raise ValueError('Imported documents cannot be deleted from the review bucket.')

    batch_id = document.batch_id
    file_path = ai_document_path(document)
    db.session.delete(document)
    db.session.flush()

    if os.path.exists(file_path):
        os.remove(file_path)

    _cleanup_batch_if_empty(batch_id)
    db.session.commit()


def bulk_delete_documents(statuses):
    allowed_statuses = {'failed', 'ignored'}
    target_statuses = [status for status in statuses if status in allowed_statuses]
    if not target_statuses:
        return 0

    documents = (
        AIExpenseDocument.query
        .filter(AIExpenseDocument.status.in_(target_statuses))
        .all()
    )

    deleted = 0
    batch_ids = set()
    for document in documents:
        batch_ids.add(document.batch_id)
        file_path = ai_document_path(document)
        db.session.delete(document)
        if os.path.exists(file_path):
            os.remove(file_path)
        deleted += 1

    db.session.flush()
    for batch_id in batch_ids:
        _cleanup_batch_if_empty(batch_id)
    db.session.commit()
    return deleted


def update_document_from_form(document, form):
    document.matched_provider_id = form.get('matched_provider_id', type=int)
    document.invoice_number = form.get('invoice_number', '').strip() or None
    document.supplier_invoice = form.get('supplier_invoice', '').strip() or None
    document.raw_supplier_name = form.get('raw_supplier_name', '').strip() or None
    document.currency_code = form.get('currency_code', '').strip() or None
    document.invoice_date = _to_date(form.get('invoice_date', '').strip())
    document.subtotal_amount = _to_decimal(form.get('subtotal_amount', '').strip())
    document.tax_amount = _to_decimal(form.get('tax_amount', '').strip())
    document.total_amount = _to_decimal(form.get('total_amount', '').strip())
    document.provider_uncertain = bool(form.get('provider_uncertain'))
    document.line_items_incomplete = bool(form.get('line_items_incomplete'))
    document.totals_mismatch = bool(form.get('totals_mismatch'))
    document.last_error = None

    for item in list(document.items):
        db.session.delete(item)
    db.session.flush()

    indexes = sorted(
        {
            int(parts[1])
            for key in form.keys()
            for parts in [key.split('-')]
            if len(parts) == 3
            and parts[0] == 'items'
            and parts[1].isdigit()
            and parts[2] == 'description'
        }
    )
    for sort_order, idx in enumerate(indexes):
        description = form.get(f'items-{idx}-description', '').strip()
        amount = _to_decimal(form.get(f'items-{idx}-amount', '').strip())
        is_tax = bool(form.get(f'items-{idx}-is_tax'))
        if not description or amount is None:
            continue
        db.session.add(AIExpenseDocumentItem(
            document_id=document.id,
            description=description,
            amount=amount,
            is_tax=is_tax,
            sort_order=sort_order,
        ))

    detect_duplicate_invoice(document)
    document.status = 'needs_review'
    db.session.commit()
    return document
