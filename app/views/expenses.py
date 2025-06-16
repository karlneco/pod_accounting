import importlib
import os
import uuid
from datetime import datetime
from decimal import Decimal

from flask import (
    Blueprint, render_template, url_for,
    redirect, flash, request, current_app
)

from ..models import db, ExpenseInvoice, Provider, ExpenseItem, Account, Order
from ..utils.currency import usd_to_cad
from ..utils.date_filters import get_date_range

bp = Blueprint('expenses', __name__, template_folder='templates/expenses')


@bp.route('/')
def list_expenses():
    # read filter params
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    account_id = request.args.get('account_id', type=int)

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end = datetime.fromisoformat(end_str).date() if end_str else None
    start_date, end_date = get_date_range(range_key, start, end)

    # pull all expense‐invoices with their provider
    q = ExpenseInvoice.query.join(Provider)
    if account_id:
        q = q.join(ExpenseItem).filter(ExpenseItem.account_id == account_id)
    q = q.order_by(ExpenseInvoice.invoice_date.desc())

    if start_date and end_date:
        q = q.filter(ExpenseInvoice.invoice_date.between(start_date, end_date))

    invoices = q.all()
    account = Account.query.get(account_id) if account_id else None

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
        account=account,
        total_cad=total_cad,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date
    )


@bp.route('/new', methods=['GET','POST'])
def create_expense():
    providers = Provider.query.order_by(Provider.name).all()
    accounts  = Account.query.order_by(Account.name).all()

    if request.method == 'POST':
        # Header fields
        provider_id      = request.form.get('provider_id', type=int)
        invoice_date_str = request.form.get('invoice_date','').strip()
        invoice_number   = request.form.get('invoice_number','').strip() or None
        supplier_invoice = request.form.get('supplier_invoice','').strip() or None
        total_amount_str = request.form.get('total_amount','0').strip()

        # Validation
        errors = []
        if not provider_id:
            errors.append("Provider is required")
        try:
            invoice_date = datetime.fromisoformat(invoice_date_str).date()
        except:
            invoice_date = None
            errors.append("Invalid date")
        try:
            total_amount = Decimal(total_amount_str)
        except:
            total_amount = None
            errors.append("Invalid total amount")

        # Parse line-items
        line_items = []
        idx = 0
        while True:
            desc = request.form.get(f"items-{idx}-description")
            if desc is None:
                break
            amt_str = request.form.get(f"items-{idx}-amount","0").strip()
            acct_id  = request.form.get(f"items-{idx}-account_id", type=int)
            try:
                amt = Decimal(amt_str)
            except:
                amt = None
                errors.append(f"Line {idx+1}: invalid amount")
            line_items.append((desc, acct_id, amt))
            idx += 1

        if not line_items:
            errors.append("At least one line item is required")

        if errors:
            for e in errors:
                flash(e,'warning')
            # re-render
            return render_template(
                'expenses/form.html',
                invoice=None,
                providers=providers,
                accounts=accounts,
                form={
                  'provider_id':provider_id,
                  'invoice_date':invoice_date_str,
                  'invoice_number':invoice_number,
                  'supplier_invoice':supplier_invoice,
                  'total_amount':total_amount_str
                },
                line_items=line_items
            )

        # Create header
        ei = ExpenseInvoice(
            provider_id=provider_id,
            invoice_date=invoice_date,
            invoice_number=invoice_number,
            supplier_invoice=supplier_invoice,
            total_amount=total_amount
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
                currency_code=Provider.query.get(provider_id).currency_code
            ))
        db.session.commit()

        flash("Expense created.", 'success')
        return redirect(url_for('expenses.show_expense', invoice_id=ei.id))

    # GET
    return render_template(
        'expenses/form.html',
        invoice=None,
        providers=providers,
        accounts=accounts,
        form={
          'provider_id':None,
          'invoice_date':'',
          'invoice_number':'',
          'supplier_invoice':'',
          'total_amount':''
        },
        line_items=[]
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
        upload_dir = os.path.join(current_app.root_path, 'uploads')
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
    return render_template('expenses/import.html', providers=providers)


@bp.route('/import/confirm', methods=['POST'])
def confirm_expenses():
    provider_id = request.form.get('provider_id', type=int)
    file_key = request.form.get('file_key')
    if not provider_id or not file_key:
        flash('Import session invalid. Start again.', 'warning')
        return redirect(url_for('expenses.import_expenses'))

    # rebuild filepath
    upload_dir = os.path.join(current_app.root_path, 'uploads')
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
                    currency_code=provider.currency_code,
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
