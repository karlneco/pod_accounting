from datetime import datetime
from decimal import Decimal

from flask import Blueprint, render_template, url_for, redirect, flash, request
from ..models import Account, db, ExpenseItem, ExpenseInvoice, Provider
from ..utils.currency import usd_to_cad
from ..utils.date_filters import get_date_range

bp = Blueprint('accounts', __name__, template_folder='templates/accounts')

@bp.route('/')
def list_accounts():
    """Show all accounts."""
    accounts = Account.query.order_by(Account.id).all()
    return render_template('accounts/list.html', accounts=accounts)

@bp.route('/new', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        name  = request.form.get('name')
        type_ = request.form.get('type')
        if not name or not type_:
            flash('Name and Type are required.', 'warning')
            return redirect(url_for('accounts.create_account'))

        existing = Account.query.filter_by(name=name).first()
        if existing:
            flash(f"Account '{name}' already exists.", 'warning')
            return redirect(url_for('accounts.list_accounts'))

        acct = Account(name=name, type=type_)
        db.session.add(acct)
        db.session.commit()
        flash(f"Account '{name}' created.", 'success')
        return redirect(url_for('accounts.list_accounts'))

    # GET: render the new account form
    return render_template('accounts/new.html')

@bp.route('/account/<int:account_id>/transactions')
def account_transactions(account_id):
    # 1) date range
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str   = request.args.get('end')

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end   = datetime.fromisoformat(end_str).date()   if end_str   else None
    start_date, end_date = get_date_range(range_key, start, end)

    # 2) load the account
    account = Account.query.get_or_404(account_id)

    # 3) fetch all ExpenseItems for this account in date range
    q = (
        db.session.query(
            ExpenseItem,
            ExpenseInvoice.invoice_date.label('date'),
            ExpenseInvoice.invoice_number.label('inv_num'),
            Provider.name.label('provider_name')
        )
        .join(ExpenseInvoice, ExpenseItem.expense_invoice_id==ExpenseInvoice.id)
        .join(Provider, ExpenseInvoice.provider_id==Provider.id)
        .filter(ExpenseItem.account_id == account_id)
    )
    if start_date and end_date:
        q = q.filter(ExpenseInvoice.invoice_date.between(start_date, end_date))

    rows = q.order_by(ExpenseInvoice.invoice_date.desc()).all()

    # 4) compute totals
    total_orig = Decimal('0')
    total_cad  = Decimal('0')
    entries = []
    for item, date, inv_num, prov in rows:
        amt = item.amount or Decimal('0')
        total_orig += amt
        cad = (usd_to_cad(amt, date) if item.currency_code!='CAD' else amt)
        total_cad += cad
        entries.append({
            'date': date,
            'invoice_number': inv_num,
            'provider': prov,
            'description': item.description,
            'amount': amt,
            'currency': item.currency_code,
            'amount_cad': cad,
            'invoice_id': item.expense_invoice_id
        })

    return render_template(
        'accounts/transactions.html',
        account=account,
        entries=entries,
        total_orig=total_orig,
        total_cad=total_cad,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date
    )
