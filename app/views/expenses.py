import importlib
import json
import os
import shutil
import uuid
from datetime import datetime
from decimal import Decimal

from flask import (
    Blueprint, render_template, url_for,
    redirect, flash, request, current_app, jsonify, send_from_directory
)
from sqlalchemy import func
from werkzeug.utils import secure_filename

from ..models import (
    db,
    ExpenseInvoice,
    ExpenseInvoiceFile,
    Provider,
    ExpenseItem,
    Account,
    Order,
    ExpenseTemplate,
    ExpenseTemplateItem,
    AIExpenseDocument,
    AIExpenseBatch,
)
from ..services.ai_expense_import import (
    DOCUMENT_STATUSES,
    ai_document_path,
    bulk_delete_documents,
    delete_document,
    document_blockers,
    get_or_create_ai_import_settings,
    ignore_document,
    import_document_to_expense,
    process_document,
    rerun_document,
    save_ai_expense_batch,
    update_document_from_form,
)
from ..utils.currency import usd_to_cad
from ..utils.date_filters import get_date_range

bp = Blueprint('expenses', __name__, template_folder='templates/expenses')


def _invoice_upload_root():
    upload_root = current_app.config.get('EXPENSE_INVOICE_UPLOAD_DIR')
    if not upload_root:
        raise RuntimeError("EXPENSE_INVOICE_UPLOAD_DIR is not configured")
    return upload_root


def _invoice_dir(invoice_id):
    return os.path.join(_invoice_upload_root(), str(invoice_id))


def _is_pdf(filename):
    return os.path.splitext(filename)[1].lower() == '.pdf'


def _ai_status_counts():
    counts = {status: 0 for status in DOCUMENT_STATUSES}
    rows = (
        db.session.query(AIExpenseDocument.status, func.count(AIExpenseDocument.id))
        .group_by(AIExpenseDocument.status)
        .all()
    )
    for status, count in rows:
        counts[status] = count
    return counts


def _save_invoice_files(invoice_id, files):
    saved = 0
    rejected = 0
    if not files:
        return saved, rejected

    os.makedirs(_invoice_dir(invoice_id), exist_ok=True)

    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        original = secure_filename(uploaded.filename)
        if not original or not _is_pdf(original):
            rejected += 1
            continue
        stored_name = f"{uuid.uuid4().hex}.pdf"
        file_path = os.path.join(_invoice_dir(invoice_id), stored_name)
        uploaded.save(file_path)
        db.session.add(ExpenseInvoiceFile(
            expense_invoice_id=invoice_id,
            stored_filename=stored_name,
            original_filename=original
        ))
        saved += 1

    return saved, rejected


@bp.route('/new', methods=['GET', 'POST'])
def create_expense():
    providers = Provider.query.order_by(Provider.name).all()
    accounts = Account.query.order_by(Account.name).all()
    templates = ExpenseTemplate.query.order_by(ExpenseTemplate.name).all()

    if request.method == 'POST':
        # Header fields
        provider_id = request.form.get('provider_id', type=int)
        invoice_date_str = request.form.get('invoice_date', '').strip()
        invoice_number = request.form.get('invoice_number', '').strip() or None
        supplier_invoice = request.form.get('supplier_invoice', '').strip() or None

        # Validation
        errors = []
        if not provider_id:
            errors.append("Provider is required")
        try:
            invoice_date = datetime.fromisoformat(invoice_date_str).date()
        except:
            invoice_date = None
            errors.append("Invalid date")

        # Parse line-items without assuming contiguous indexes.
        line_item_indexes = sorted(
            {
                int(parts[1])
                for key in request.form.keys()
                for parts in [key.split('-')]
                if len(parts) == 3
                and parts[0] == 'items'
                and parts[1].isdigit()
                and parts[2] == 'description'
            }
        )

        line_items = []
        for idx in line_item_indexes:
            desc = (request.form.get(f"items-{idx}-description") or '').strip()
            amt_str = (request.form.get(f"items-{idx}-amount") or '').strip()
            acct_id = request.form.get(f"items-{idx}-account_id", type=int)

            if not desc and not amt_str and not acct_id:
                continue

            try:
                amt = Decimal(amt_str)
            except:
                amt = None
                errors.append(f"Line {len(line_items) + 1}: invalid amount")

            if not acct_id:
                errors.append(f"Line {len(line_items) + 1}: account is required")

            line_items.append((desc, acct_id, amt))

        if not line_items:
            errors.append("At least one line item is required")

        if errors:
            for e in errors:
                flash(e, 'warning')
            # re-render
            return render_template(
                'expenses/form.html',
                invoice=None,
                providers=providers,
                accounts=accounts,
                form={
                    'provider_id': provider_id,
                    'invoice_date': invoice_date_str,
                    'invoice_number': invoice_number,
                    'supplier_invoice': supplier_invoice,
                },
                line_items=line_items,
                templates=templates
            )

        # Create header
        ei = ExpenseInvoice(
            provider_id=provider_id,
            invoice_date=invoice_date,
            invoice_number=invoice_number,
            supplier_invoice=supplier_invoice,
            total_amount=0
        )
        db.session.add(ei)
        db.session.flush()

        # Create each ExpenseItem
        for desc, acct_id, amt in line_items:
            db.session.add(ExpenseItem(
                expense_invoice_id=ei.id,
                account_id=acct_id,
                description=desc,
                amount=amt,
                currency_code=Provider.query.get(provider_id).currency_code,
                order_id=invoice_number
            ))

        subtotal = sum(amt for _, _, amt in line_items)
        # if CAD, add GST
        prov = Provider.query.get(provider_id)
        if prov.currency_code == 'CAD':
            gst = (subtotal * Decimal('0.05')).quantize(Decimal('0.01'))

        else:
            gst = Decimal('0')

        # Add GST as its own line-item
        if gst and gst != Decimal('0'):
            gst_acc = Account.query.filter_by(name='GST Paid').first()
            db.session.add(ExpenseItem(
                expense_invoice_id=ei.id,
                account_id=gst_acc.id if gst_acc else None,
                description='GST',
                amount=gst,
                currency_code=prov.currency_code,
                order_id=invoice_number
            ))

        ei.total_amount = subtotal + gst
        saved, rejected = _save_invoice_files(
            ei.id,
            request.files.getlist('invoice_pdfs')
        )
        db.session.commit()
        db.session.flush()

        if rejected:
            flash(f"{rejected} file(s) were skipped (PDF only).", 'warning')
        if saved:
            flash(f"Uploaded {saved} PDF(s).", 'success')

        flash("Expense created.", 'success')
        return redirect(url_for('expenses.show_expense', invoice_id=ei.id))

    # GET
    return render_template(
        'expenses/form.html',
        invoice=None,
        providers=providers,
        accounts=accounts,
        form={
            'provider_id': None,
            'invoice_date': '',
            'invoice_number': '',
            'supplier_invoice': '',
            'total_amount': ''
        },
        line_items=[],
        templates=templates

    )


@bp.route('/')
def list_expenses():
    # read filter params
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    provider_id = request.args.get('provider_id', type=int)
    account_id = request.args.get('account_id', type=int)

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end = datetime.fromisoformat(end_str).date() if end_str else None
    start_date, end_date = get_date_range(range_key, start, end)

    # pull all expense‐invoices with their provider
    q = ExpenseInvoice.query.join(Provider)
    if provider_id:
        q = q.filter(ExpenseInvoice.provider_id == provider_id)
    if account_id:
        q = q.join(ExpenseItem).filter(ExpenseItem.account_id == account_id)
    q = q.order_by(ExpenseInvoice.invoice_date.desc())

    if start_date and end_date:
        q = q.filter(ExpenseInvoice.invoice_date.between(start_date, end_date))

    invoices = q.distinct().all()
    provider = Provider.query.get(provider_id) if provider_id else None
    account = Account.query.get(account_id) if account_id else None
    providers = Provider.query.order_by(Provider.name).all()
    accounts = Account.query.order_by(Account.name).all()

    # compute grand‐total in CAD
    total_cad = 0
    for inv in invoices:
        amt = inv.total_amount
        # if original was USD, convert
        if inv.provider.currency_code != 'CAD':
            amt = usd_to_cad(amt, inv.invoice_date)
        total_cad += amt

    return render_template(
        'expenses/list.html',
        invoices=invoices,
        providers=providers,
        accounts=accounts,
        provider=provider,
        account=account,
        total_cad=total_cad,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date
    )


@bp.route('/import', methods=['GET', 'POST'])
def import_expenses():
    # load suppliers for the dropdown
    providers = Provider.query.order_by(Provider.name).all()

    if request.method == 'POST':
        provider_id = request.form.get('provider_id', type=int)
        uploaded = request.files.get('file')
        if not provider_id or not uploaded:
            flash('Supplier and file are required.', 'warning')
            return redirect(url_for('expenses.import_expenses'))

        # persist upload
        upload_dir = current_app.config['IMPORT_UPLOAD_DIR']
        os.makedirs(upload_dir, exist_ok=True)
        file_key = f"{uuid.uuid4().hex}.csv"
        file_path = os.path.join(upload_dir, file_key)
        uploaded.save(file_path)

        # pick the importer module dynamically
        provider = Provider.query.get_or_404(provider_id)
        importer_name = provider.importer or 'generic'  # fallback importer
        module = importlib.import_module(f'app.importers.{importer_name}')
        invoices, missing = module.parse(file_path, provider_id)
        for payee in missing:
            flash(f"No matching provider found for “{payee}”; row skipped.", 'warning')

        # mark which invoices have a matching order_number in our DB
        existing_orders = {o.order_number for o in Order.query.with_entities(Order.order_number)}
        for inv in invoices:
            inv['order_exists'] = (inv['invoice_number'] in existing_orders)

        # render a verify page listing each invoice + its items
        return render_template(
            'expenses/verify.html',
            file_key=file_key,
            provider=provider,
            invoices=invoices
        )

    # GET: show import form
    return render_template(
        'expenses/import.html',
        providers=providers,
        ai_status_counts=_ai_status_counts()
    )


@bp.route('/import/ai', methods=['POST'])
def import_expenses_ai():
    provider_hint_id = request.form.get('provider_hint_id', type=int)
    uploaded_files = request.files.getlist('files')

    valid_files = [
        uploaded for uploaded in uploaded_files
        if uploaded and uploaded.filename and _is_pdf(uploaded.filename)
    ]
    if not valid_files:
        flash('At least one PDF is required for AI import.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    batch, documents = save_ai_expense_batch(valid_files, provider_hint_id=provider_hint_id)
    if batch is None:
        flash('No valid PDFs were uploaded.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    flash(f'Queued {len(documents)} PDF(s) for AI review.', 'success')
    return redirect(url_for('expenses.ai_review_bucket'))


@bp.route('/review-bucket')
def ai_review_bucket():
    status = request.args.get('status', '').strip()
    batch_id = request.args.get('batch_id', type=int)

    query = AIExpenseDocument.query.order_by(AIExpenseDocument.uploaded_at.desc(), AIExpenseDocument.id.desc())
    if status and status in DOCUMENT_STATUSES:
        query = query.filter(AIExpenseDocument.status == status)
    if batch_id:
        query = query.filter(AIExpenseDocument.batch_id == batch_id)

    documents = query.all()
    return render_template(
        'expenses/ai_review_list.html',
        documents=documents,
        status=status,
        batch_id=batch_id,
        status_counts=_ai_status_counts(),
        statuses=DOCUMENT_STATUSES,
    )


@bp.route('/review-bucket/<int:document_id>')
def ai_review_detail(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    providers = Provider.query.order_by(Provider.name).all()
    blockers = document_blockers(document)
    return render_template(
        'expenses/ai_review_detail.html',
        document=document,
        providers=providers,
        blockers=blockers,
    )


@bp.route('/review-bucket/<int:document_id>/save', methods=['POST'])
def ai_review_save(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    update_document_from_form(document, request.form)
    flash('Draft updated.', 'success')
    return redirect(url_for('expenses.ai_review_detail', document_id=document_id))


@bp.route('/review-bucket/<int:document_id>/rerun', methods=['POST'])
def ai_review_rerun(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    rerun_document(document)
    flash('Document re-queued for AI extraction.', 'success')
    return redirect(url_for('expenses.ai_review_detail', document_id=document_id))


@bp.route('/review-bucket/<int:document_id>/ignore', methods=['POST'])
def ai_review_ignore(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    ignore_document(document)
    flash('Document ignored.', 'success')
    return redirect(url_for('expenses.ai_review_bucket'))


@bp.route('/review-bucket/<int:document_id>/delete', methods=['POST'])
def ai_review_delete(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    try:
        delete_document(document)
    except ValueError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('expenses.ai_review_detail', document_id=document_id))

    flash('Draft deleted from the review bucket.', 'success')
    return redirect(url_for('expenses.ai_review_bucket'))


@bp.route('/review-bucket/clear', methods=['POST'])
def ai_review_clear():
    statuses = request.form.getlist('statuses')
    deleted = bulk_delete_documents(statuses)
    if deleted:
        flash(f'Deleted {deleted} document(s) from the review bucket.', 'success')
    else:
        flash('No matching documents were deleted.', 'warning')
    return redirect(url_for('expenses.ai_review_bucket'))


@bp.route('/review-bucket/<int:document_id>/import', methods=['POST'])
def ai_review_import(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    try:
        invoice = import_document_to_expense(document)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
        return redirect(url_for('expenses.ai_review_detail', document_id=document_id))

    flash('AI expense imported.', 'success')
    return redirect(url_for('expenses.show_expense', invoice_id=invoice.id))


@bp.route('/review-bucket/<int:document_id>/process', methods=['POST'])
def ai_review_process(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    if document.status not in {'queued', 'failed'}:
        flash('Only queued or failed documents can be processed directly.', 'warning')
        return redirect(url_for('expenses.ai_review_detail', document_id=document_id))

    if process_document(document.id):
        flash('Document processed.', 'success')
    else:
        flash('Document processing failed. Check the last error.', 'warning')
    return redirect(url_for('expenses.ai_review_detail', document_id=document_id))


@bp.route('/review-bucket/<int:document_id>/file')
def ai_review_download(document_id):
    document = AIExpenseDocument.query.get_or_404(document_id)
    return send_from_directory(
        os.path.dirname(ai_document_path(document)),
        os.path.basename(ai_document_path(document)),
        as_attachment=True,
        download_name=document.original_filename
    )


@bp.route('/import/confirm', methods=['POST'])
def confirm_expenses():
    provider_id = request.form.get('provider_id', type=int)
    file_key = request.form.get('file_key')
    if not provider_id or not file_key:
        flash('Import session invalid. Start again.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    # rebuild filepath
    upload_dir = current_app.config['IMPORT_UPLOAD_DIR']
    filepath = os.path.join(upload_dir, file_key)
    if not os.path.exists(filepath):
        flash('Upload expired. Please re-upload.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    # find the provider & its chosen importer
    provider = Provider.query.get_or_404(provider_id)
    importer_name = provider.importer or 'generic'
    module = importlib.import_module(f'app.importers.{importer_name}')
    invoices, missing = module.parse(filepath, provider_id)

    created = 0
    for inv in invoices:
        if inv['action'] == 'skip':
            continue
        elif inv['action'] == 'update':
            ei = ExpenseInvoice.query.get(inv['existing_id'])
            ei.invoice_date = inv['invoice_date']
            ei.total_amount = inv['total_amount']
            db.session.add(ei)
        else:
            # create the invoice header
            ei = ExpenseInvoice(
                provider_id=inv['provider_id'],
                invoice_date=inv['invoice_date'],
                invoice_number=inv['invoice_number'],
                supplier_invoice=inv['supplier_invoice'],
                total_amount=inv['total_amount']
            )
            db.session.add(ei)
            db.session.flush()  # get ei.id

        # create each line-item with its proper account & currency
        for item in inv['items']:
            acct = item['account_id']
            desc = item['description']  # "Daily Ad Spend" or "GST"
            amt = item['amount']  # Decimal

            if inv['action'] == 'update':
                # try to find an existing ExpenseItem by invoice_id + description
                existing_invoice = ExpenseItem.query.filter_by(
                    expense_invoice_id=inv['existing_id'],
                    description=desc
                ).first()

                if existing_invoice:
                    # update the amount (and currency, if you want)
                    existing_invoice.amount = amt
                    existing_invoice.currency_code = provider.currency_code
                    db.session.add(existing_invoice)
            else:
                ei_line = ExpenseItem(
                    expense_invoice_id=ei.id,
                    account_id=acct,
                    description=item['description'],
                    amount=item['amount'],
                    currency_code=item['currency_code'],
                    order_id=inv['invoice_number'],
                )
                db.session.add(ei_line)

        created += 1

    db.session.commit()
    os.remove(filepath)

    flash(f'Successfully imported {created} expense invoices.', 'success')
    return redirect(url_for('expenses.list_expenses'))


@bp.route('/<int:invoice_id>')
def show_expense(invoice_id):
    invoice = ExpenseInvoice.query.get_or_404(invoice_id)
    return render_template('expenses/detail.html', invoice=invoice)


@bp.route('/<int:invoice_id>/delete', methods=['POST'])
def delete_expense(invoice_id):
    invoice = ExpenseInvoice.query.get_or_404(invoice_id)
    invoice_dir = _invoice_dir(invoice.id)

    db.session.delete(invoice)
    db.session.commit()

    shutil.rmtree(invoice_dir, ignore_errors=True)
    flash("Expense deleted.", "success")
    return redirect(url_for('expenses.list_expenses'))


@bp.route('/<int:invoice_id>/files', methods=['POST'])
def upload_expense_files(invoice_id):
    invoice = ExpenseInvoice.query.get_or_404(invoice_id)
    files = request.files.getlist('invoice_pdfs')
    if not files or all(not f.filename for f in files):
        flash('Please choose at least one PDF.', 'warning')
        return redirect(url_for('expenses.show_expense', invoice_id=invoice_id))

    saved, rejected = _save_invoice_files(invoice.id, files)
    db.session.commit()

    if rejected:
        flash(f"{rejected} file(s) were skipped (PDF only).", 'warning')
    if saved:
        flash(f"Uploaded {saved} PDF(s).", 'success')
    return redirect(url_for('expenses.show_expense', invoice_id=invoice_id))


@bp.route('/<int:invoice_id>/files/<int:file_id>')
def download_expense_file(invoice_id, file_id):
    file = ExpenseInvoiceFile.query.filter_by(
        id=file_id,
        expense_invoice_id=invoice_id
    ).first_or_404()
    return send_from_directory(
        _invoice_dir(invoice_id),
        file.stored_filename,
        as_attachment=True,
        download_name=file.original_filename
    )


@bp.route('/templates/create', methods=['POST'])
def create_template():
    name = request.form.get('template_name', '').strip()
    provider_id = request.form.get('provider_id', type=int)
    raw = request.form.get('template_items', '[]')
    try:
        data = json.loads(raw)
    except:
        flash('Could not parse template data', 'warning')
        return redirect(request.referrer)

    tmpl = ExpenseTemplate(name=name, provider_id=provider_id)
    db.session.add(tmpl)
    db.session.flush()
    for idx, it in enumerate(data):
        ti = ExpenseTemplateItem(
            template_id=tmpl.id,
            description=it['description'],
            account_id=int(it['account_id']),
            amount=Decimal(it['amount']),
            order=idx
        )
        db.session.add(ti)
    db.session.commit()
    flash(f'Template "{name}" saved.', 'success')
    return redirect(request.referrer)


@bp.route('/templates/<int:template_id>/update', methods=['POST'])
def update_template(template_id):
    tmpl = ExpenseTemplate.query.get_or_404(template_id)
    provider_id = request.form.get('provider_id', type=int)
    raw = request.form.get('template_items', '[]')
    try:
        data = json.loads(raw)
    except:
        flash('Could not parse template data', 'warning')
        return redirect(request.referrer)

    # Update provider
    tmpl.provider_id = provider_id

    # Delete existing items
    for item in tmpl.items:
        db.session.delete(item)
    db.session.flush()

    # Create new items
    for idx, it in enumerate(data):
        ti = ExpenseTemplateItem(
            template_id=tmpl.id,
            description=it['description'],
            account_id=int(it['account_id']),
            amount=Decimal(it['amount']),
            order=idx
        )
        db.session.add(ti)
    
    db.session.commit()
    flash(f'Template "{tmpl.name}" updated.', 'success')
    return redirect(request.referrer)


# JSON End points ------------------8<---------------------------------
@bp.route('/provider/<int:provider_id>/last_invoice_items')
def last_invoice_items(provider_id):
    # grab the very last invoice for that provider
    last = (
        ExpenseInvoice.query
        .filter_by(provider_id=provider_id)
        .order_by(ExpenseInvoice.invoice_date.desc())
        .first()
    )
    if not last:
        return jsonify(items=[], currency_code=None)

    items = [
        {
            'description': li.description,
            'account_id': li.account_id,
            'amount': str(li.amount)
        }
        for li in last.items
    ]
    prov = Provider.query.get(provider_id)
    return jsonify(items=items, currency_code=prov.currency_code)


@bp.route('/templates/<int:template_id>')
def get_template(template_id):
    tmpl = ExpenseTemplate.query.get_or_404(template_id)
    items = [
        {
            'description': it.description,
            'account_id': it.account_id,
            'amount': str(it.amount)
        }
        for it in tmpl.items
    ]
    return jsonify(items=items, provider_id=tmpl.provider_id)
