from decimal import Decimal
from flask import Blueprint, render_template, request
from datetime import datetime
from sqlalchemy import func, or_
from ..models import db, Account, Order, OrderItem, ExpenseInvoice, ExpenseItem
from ..utils.date_filters import get_date_range
from ..utils.currency import usd_to_cad

bp = Blueprint('reports', __name__, template_folder='templates/reports')

@bp.route('/pl')
def pl_report():
    # 1) Date‐range filter
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str   = request.args.get('end')

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end   = datetime.fromisoformat(end_str).date()   if end_str   else None
    start_date, end_date = get_date_range(range_key, start, end)

    # 2) Income — fetch every OrderItem with its currency and date
    inc_rows = (
        db.session.query(
            Account.name,
            OrderItem.subtotal,
            OrderItem.currency_code,
            Order.order_date
        )
        .join(Account, OrderItem.account_id==Account.id)
        .join(Order, OrderItem.order_id==Order.id)
        .filter(Account.type=='Income')
        .filter(
            Order.order_date.between(start_date, end_date)
            if start_date and end_date else True
        )
        .all()
    )

    # sum into CAD per account
    income_map = {}
    for acc_name, amt, curr, odt in inc_rows:
        cad = usd_to_cad(amt, odt) if curr != 'CAD' else amt
        income_map[acc_name] = income_map.get(acc_name, Decimal('0')) + cad

    income        = sorted(income_map.items(), key=lambda x: x[0])
    total_income  = sum(val for _, val in income)

    # 3) COGS — all ExpenseItems on COGS accounts
    cogs_rows = (
        db.session.query(
            Account.name,
            ExpenseItem.amount,
            ExpenseItem.currency_code,
            ExpenseInvoice.invoice_date
        )
        .join(Account, ExpenseItem.account_id==Account.id)
        .join(ExpenseInvoice, ExpenseItem.expense_invoice_id==ExpenseInvoice.id)
        .filter(Account.type=='COGS')
        .filter(
            ExpenseInvoice.invoice_date.between(start_date, end_date)
            if start_date and end_date else True
        )
        .all()
    )

    cogs_map = {}
    for acc_name, amt, curr, idt in cogs_rows:
        cad = usd_to_cad(amt, idt) if curr != 'CAD' else amt
        cogs_map[acc_name] = cogs_map.get(acc_name, Decimal('0')) + cad

    cogs        = sorted(cogs_map.items(), key=lambda x: x[0])
    total_cogs  = sum(val for _, val in cogs)

    gross_profit = total_income - total_cogs

    # 4) Expenses — all ExpenseItems on Expense accounts
    exp_rows = (
        db.session.query(
            Account.id.label('account_id'),
            Account.name,
            ExpenseItem.amount,
            ExpenseItem.currency_code,
            ExpenseInvoice.invoice_date
        )
        .join(Account, ExpenseItem.account_id==Account.id)
        .join(ExpenseInvoice, ExpenseItem.expense_invoice_id==ExpenseInvoice.id)
        .filter(Account.type.in_(['Expense', 'Fees']))
        .filter(
            ExpenseInvoice.invoice_date.between(start_date, end_date)
            if start_date and end_date else True
        )
        .all()
    )

    exp_map = {}
    for acc_id, acc_name, amt, curr, idt in exp_rows:
        cad = usd_to_cad(amt, idt) if curr != 'CAD' else amt
        key = (acc_id, acc_name)
        exp_map[key] = exp_map.get(key, Decimal('0')) + cad

    expenses = [
        {'id': aid, 'name': aname, 'total': total}
        for (aid, aname), total in sorted(exp_map.items(), key=lambda x: x[0][1])
    ]
    total_expenses = sum(e['total'] for e in expenses)

    net_profit = gross_profit - total_expenses

    return render_template(
        'reports/pl.html',
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        income=income,
        total_income=total_income,
        cogs=cogs,
        total_cogs=total_cogs,
        gross_profit=gross_profit,
        expenses=expenses,
        total_expenses=total_expenses,
        net_profit=net_profit
    )
