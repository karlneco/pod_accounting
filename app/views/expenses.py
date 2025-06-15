import importlib
import os
import uuid
from datetime import datetime

from flask import (
    Blueprint, render_template, url_for,
    redirect, flash, request, current_app
)
from ..models import db, ExpenseInvoice, Provider, ExpenseItem, Account, Order
from ..utils.date_filters import get_date_range

bp = Blueprint('expenses', __name__, template_folder='templates/expenses')


@bp.route('/')
def list_expenses():
    # read filter params
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end = datetime.fromisoformat(end_str).date() if end_str else None
    start_date, end_date = get_date_range(range_key, start, end)

    # pull all expense‐invoices with their provider
    q = (
        ExpenseInvoice.query
        .join(Provider)
        .order_by(ExpenseInvoice.invoice_date.desc())
    )

    if start_date and end_date:
        q = q.filter(ExpenseInvoice.invoice_date.between(start_date, end_date))

    invoices = q.all()

    return render_template('expenses/list.html', invoices=invoices)


@bp.route('/new', methods=['GET', 'POST'])
def create_expense():
    if request.method == 'POST':
        flash('Expense creation not implemented yet', 'info')
        return redirect(url_for('expenses.list_expenses'))
    return render_template('expenses/new.html')


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
        upload_dir = os.path.join(current_app.root_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        file_key = f"{uuid.uuid4().hex}.csv"
        file_path = os.path.join(upload_dir, file_key)
        uploaded.save(file_path)

        # pick the importer module dynamically
        provider = Provider.query.get_or_404(provider_id)
        importer_name = provider.importer or 'generic'  # fallback importer
        module = importlib.import_module(f'app.importers.{importer_name}')
        invoices = module.parse(file_path, provider_id)

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
    return render_template('expenses/import.html', providers=providers)


@bp.route('/import/confirm', methods=['POST'])
def confirm_expenses():
    provider_id = request.form.get('provider_id', type=int)
    file_key    = request.form.get('file_key')
    if not provider_id or not file_key:
        flash('Import session invalid. Start again.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    # rebuild filepath
    upload_dir = os.path.join(current_app.root_path, 'uploads')
    filepath   = os.path.join(upload_dir, file_key)
    if not os.path.exists(filepath):
        flash('Upload expired. Please re-upload.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    # find the provider & its chosen importer
    provider      = Provider.query.get_or_404(provider_id)
    importer_name = provider.importer or 'printify'
    module        = importlib.import_module(f'app.importers.{importer_name}')
    invoices      = module.parse(filepath, provider_id)

    # look up the three COGS accounts
    acct_cogs         = Account.query.filter_by(name='COGS').first()
    acct_cogs_ship    = Account.query.filter_by(name='COGS Shipping').first()
    acct_cogs_tax     = Account.query.filter_by(name='COGS Tax').first()
    # fallback if missing
    acct_map = {
        'Production Cost':      acct_cogs,
        'Shipping Cost':     acct_cogs_ship,
        'Sales Tax Charged': acct_cogs_tax,
    }

    created = 0
    for inv in invoices:
        # create the invoice header
        ei = ExpenseInvoice(
            provider_id      = inv['provider_id'],
            invoice_date     = inv['invoice_date'],
            invoice_number   = inv['invoice_number'],
            supplier_invoice = inv['supplier_invoice'],
            total_amount     = inv['total_amount']
        )
        db.session.add(ei)
        db.session.flush()  # get ei.id

        # create each line-item with its proper account & currency
        for item in inv['items']:
            acct = acct_map.get(item['description'])
            ei_line = ExpenseItem(
                expense_invoice_id = ei.id,
                account_id         = acct.id if acct else None,
                description        = item['description'],
                amount             = item['amount'],
                currency_code      = provider.currency_code,
                order_id           = inv['invoice_number'],
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
