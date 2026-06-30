import csv
import io
from decimal import Decimal
from datetime import datetime, timedelta

from flask import Blueprint, Response, render_template, request
from sqlalchemy import func

from ..models import db, Account, Order, OrderItem, ExpenseInvoice, ExpenseItem
from ..utils.currency import usd_to_cad
from ..utils.date_filters import get_date_range

bp = Blueprint('reports', __name__, template_folder='templates/reports')


def get_period_columns(start_date, end_date, granularity):
    """Generate column headers for the selected time granularity"""
    columns = []
    current = start_date

    while current <= end_date:
        if granularity == 'day':
            columns.append({
                'key': current.strftime('%Y-%m-%d'),
                'label': current.strftime('%b %d'),
                'date': current
            })
            current += timedelta(days=1)
        elif granularity == 'week':
            # Start of week (Monday)
            week_start = current - timedelta(days=current.weekday())
            week_end = week_start + timedelta(days=6)
            columns.append({
                'key': week_start.strftime('%Y-%m-%d'),
                'label': f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}",
                'date': week_start
            })
            current += timedelta(days=7)
        elif granularity == 'month':
            month_start = current.replace(day=1)
            columns.append({
                'key': month_start.strftime('%Y-%m'),
                'label': month_start.strftime('%b %Y'),
                'date': month_start
            })
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    return columns


def get_date_grouping(granularity):
    """Get SQLAlchemy expression for grouping dates by granularity"""
    if granularity == 'day':
        return func.strftime('%Y-%m-%d', Order.order_date)
    elif granularity == 'week':
        # Use the same date format as the column keys
        return func.strftime('%Y-%m-%d', Order.order_date)
    elif granularity == 'month':
        # SQLite: group by month using strftime
        return func.strftime('%Y-%m', Order.order_date)
    else:
        return func.strftime('%Y-%m-%d', Order.order_date)


def get_expense_date_grouping(granularity):
    """Get SQLAlchemy expression for grouping expense dates by granularity"""
    if granularity == 'day':
        return func.strftime('%Y-%m-%d', ExpenseInvoice.invoice_date)
    elif granularity == 'week':
        # Use the same date format as the column keys
        return func.strftime('%Y-%m-%d', ExpenseInvoice.invoice_date)
    elif granularity == 'month':
        # SQLite: group by month using strftime
        return func.strftime('%Y-%m', ExpenseInvoice.invoice_date)
    else:
        return func.strftime('%Y-%m-%d', ExpenseInvoice.invoice_date)


def _parse_pl_filters():
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    granularity = request.args.get('granularity', 'month')  # day, week, month

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end = datetime.fromisoformat(end_str).date() if end_str else None
    start_date, end_date = get_date_range(range_key, start, end)

    return range_key, start_date, end_date, granularity


def _build_pl_report_data(start_date, end_date, granularity):
    # Generate period columns
    period_columns = get_period_columns(start_date, end_date, granularity)

    # 2) Income — fetch every OrderItem grouped by period
    income_query = (
        db.session.query(
            Account.name,
            get_date_grouping(granularity).label('period'),
            func.sum(OrderItem.subtotal).label('amount'),
            OrderItem.currency_code,
            Order.order_date.label('order_date')  # Get actual order date for each row
        )
        .join(Account, OrderItem.account_id == Account.id)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Account.type == 'Income')
        .filter(Order.order_date.between(start_date, end_date))
        .group_by(Account.name, get_date_grouping(granularity), OrderItem.currency_code, Order.order_date)
        .all()
    )

    # Process income data into period columns
    income_data = {}
    for acc_name, period, amt, curr, order_date in income_query:
        if acc_name not in income_data:
            income_data[acc_name] = {}

        # Convert to CAD using the actual order date
        cad = usd_to_cad(amt, order_date) if curr != 'CAD' else amt

        # For weekly granularity, map the date to the week start date
        if granularity == 'week':
            # Convert period string back to date, then find week start
            period_date = datetime.strptime(period, '%Y-%m-%d').date()
            week_start = period_date - timedelta(days=period_date.weekday())
            period_key = week_start.strftime('%Y-%m-%d')
        else:
            period_key = period

        income_data[acc_name][period_key] = income_data[acc_name].get(period_key, Decimal('0')) + cad

    # Order counts query
    order_count_query = (
        db.session.query(
            get_date_grouping(granularity).label('period'),
            func.count(Order.id).label('order_count')
        )
        .filter(Order.order_date.between(start_date, end_date))
        .group_by(get_date_grouping(granularity))
        .all()
    )

    # Process order count data
    order_counts_by_period = {}
    for period, count in order_count_query:
        if granularity == 'week':
            period_date = datetime.strptime(period, '%Y-%m-%d').date()
            week_start = period_date - timedelta(days=period_date.weekday())
            period_key = week_start.strftime('%Y-%m-%d')
            order_counts_by_period[period_key] = order_counts_by_period.get(period_key, 0) + count
        else:
            order_counts_by_period[period] = count

    # 3) COGS — all ExpenseItems grouped by period
    cogs_query = (
        db.session.query(
            Account.name,
            get_expense_date_grouping(granularity).label('period'),
            func.sum(ExpenseItem.amount).label('amount'),
            ExpenseItem.currency_code,
            ExpenseInvoice.invoice_date.label('invoice_date')  # Get actual invoice date for each row
        )
        .join(Account, ExpenseItem.account_id == Account.id)
        .join(ExpenseInvoice, ExpenseItem.expense_invoice_id == ExpenseInvoice.id)
        .filter(Account.type == 'COGS')
        .filter(ExpenseInvoice.invoice_date.between(start_date, end_date))
        .group_by(Account.name, get_expense_date_grouping(granularity), ExpenseItem.currency_code, ExpenseInvoice.invoice_date)
        .all()
    )

    # Process COGS data
    cogs_data = {}
    for acc_name, period, amt, curr, invoice_date in cogs_query:
        if acc_name not in cogs_data:
            cogs_data[acc_name] = {}

        # Convert to CAD using the actual invoice date
        cad = usd_to_cad(amt, invoice_date) if curr != 'CAD' else amt

        # For weekly granularity, map the date to the week start date
        if granularity == 'week':
            period_date = datetime.strptime(period, '%Y-%m-%d').date()
            week_start = period_date - timedelta(days=period_date.weekday())
            period_key = week_start.strftime('%Y-%m-%d')
        else:
            period_key = period

        cogs_data[acc_name][period_key] = cogs_data[acc_name].get(period_key, Decimal('0')) + cad

    # 4) Expenses — all ExpenseItems grouped by period
    exp_query = (
        db.session.query(
            Account.id.label('account_id'),
            Account.name,
            get_expense_date_grouping(granularity).label('period'),
            func.sum(ExpenseItem.amount).label('amount'),
            ExpenseItem.currency_code,
            ExpenseInvoice.invoice_date.label('invoice_date')  # Get actual invoice date for each row
        )
        .join(Account, ExpenseItem.account_id == Account.id)
        .join(ExpenseInvoice, ExpenseItem.expense_invoice_id == ExpenseInvoice.id)
        .filter(Account.type.in_(['Expense', 'Fees']))
        .filter(ExpenseInvoice.invoice_date.between(start_date, end_date))
        .group_by(Account.id, Account.name, get_expense_date_grouping(granularity), ExpenseItem.currency_code, ExpenseInvoice.invoice_date)
        .all()
    )

    # Process expense data
    exp_data = {}
    for acc_id, acc_name, period, amt, curr, invoice_date in exp_query:
        key = (acc_id, acc_name)
        if key not in exp_data:
            exp_data[key] = {}

        # Convert to CAD using the actual invoice date
        cad = usd_to_cad(amt, invoice_date) if curr != 'CAD' else amt

        # For weekly granularity, map the date to the week start date
        if granularity == 'week':
            period_date = datetime.strptime(period, '%Y-%m-%d').date()
            week_start = period_date - timedelta(days=period_date.weekday())
            period_key = week_start.strftime('%Y-%m-%d')
        else:
            period_key = period

        exp_data[key][period_key] = exp_data[key].get(period_key, Decimal('0')) + cad

    # Accounts whose spend counts as advertising for blended ROAS.
    AD_SPEND_ACCOUNTS = {'Advertising Expense'}

    # Calculate totals for each period
    period_totals = {
        'income': {},
        'cogs': {},
        'expenses': {},
        'gross_profit': {},
        'net_profit': {}
    }

    for col in period_columns:
        period_key = col['key']

        # Income total for this period
        period_income = sum(
            income_data.get(acc, {}).get(period_key, Decimal('0'))
            for acc in income_data
        )
        period_totals['income'][period_key] = period_income

        # COGS total for this period
        period_cogs = sum(
            cogs_data.get(acc, {}).get(period_key, Decimal('0'))
            for acc in cogs_data
        )
        period_totals['cogs'][period_key] = period_cogs

        # Expenses total for this period
        period_expenses = sum(
            exp_data.get(key, {}).get(period_key, Decimal('0'))
            for key in exp_data
        )
        period_totals['expenses'][period_key] = period_expenses

        # Gross profit for this period
        period_totals['gross_profit'][period_key] = period_income - period_cogs

        # Net profit for this period
        period_totals['net_profit'][period_key] = period_income - period_cogs - period_expenses

    # Blended ROAS = total revenue (income) / total advertising spend, per period.
    ad_spend_by_period = {}
    for (acc_id, acc_name), periods in exp_data.items():
        if acc_name in AD_SPEND_ACCOUNTS:
            for period_key, amt in periods.items():
                ad_spend_by_period[period_key] = ad_spend_by_period.get(period_key, Decimal('0')) + amt

    roas_by_period = {}
    for col in period_columns:
        period_key = col['key']
        spend = ad_spend_by_period.get(period_key, Decimal('0'))
        income = period_totals['income'].get(period_key, Decimal('0'))
        roas_by_period[period_key] = (income / spend) if spend and spend != 0 else None

    total_ad_spend = sum(ad_spend_by_period.values())
    total_income = sum(period_totals['income'].values())
    roas_total = (total_income / total_ad_spend) if total_ad_spend and total_ad_spend != 0 else None

    # Prepare data for template
    income = [
        {
            'name': acc_name,
            'periods': {col['key']: income_data[acc_name].get(col['key'], Decimal('0')) for col in period_columns},
            'total': sum(income_data[acc_name].values())
        }
        for acc_name in sorted(income_data.keys())
    ]

    cogs = [
        {
            'name': acc_name,
            'periods': {col['key']: cogs_data[acc_name].get(col['key'], Decimal('0')) for col in period_columns},
            'total': sum(cogs_data[acc_name].values())
        }
        for acc_name in sorted(cogs_data.keys())
    ]

    expenses = [
        {
            'id': acc_id,
            'name': acc_name,
            'periods': {col['key']: exp_data[(acc_id, acc_name)].get(col['key'], Decimal('0')) for col in period_columns},
            'total': sum(exp_data[(acc_id, acc_name)].values())
        }
        for (acc_id, acc_name) in sorted(exp_data.keys(), key=lambda x: x[1])
    ]

    return {
        'period_columns': period_columns,
        'income': income,
        'cogs': cogs,
        'expenses': expenses,
        'period_totals': period_totals,
        'order_counts_by_period': order_counts_by_period,
        'roas_by_period': roas_by_period,
        'roas_total': roas_total,
    }


@bp.route('/pl')
def pl_report():
    range_key, start_date, end_date, granularity = _parse_pl_filters()
    data = _build_pl_report_data(start_date, end_date, granularity)

    return render_template(
        'reports/pl.html',
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        **data,
    )


@bp.route('/pl/export.csv')
def pl_report_csv():
    range_key, start_date, end_date, granularity = _parse_pl_filters()
    data = _build_pl_report_data(start_date, end_date, granularity)

    period_columns = data['period_columns']
    period_totals = data['period_totals']

    output = io.StringIO()
    writer = csv.writer(output)

    header = ['Section', 'Account'] + [col['key'] for col in period_columns] + ['Total']
    writer.writerow(header)

    def write_currency_row(section, account, periods_map, total):
        row = [section, account]
        for col in period_columns:
            row.append(f"{periods_map.get(col['key'], Decimal('0')):.2f}")
        row.append(f"{total:.2f}")
        writer.writerow(row)

    # Income
    order_row = ['Income', 'Number of Orders']
    for col in period_columns:
        order_row.append(str(data['order_counts_by_period'].get(col['key'], 0)))
    order_row.append(str(sum(data['order_counts_by_period'].values())))
    writer.writerow(order_row)

    roas_row = ['Income', 'Blended ROAS']
    for col in period_columns:
        roas = data['roas_by_period'].get(col['key'])
        roas_row.append(f"{roas:.2f}" if roas is not None else '')
    roas_row.append(f"{data['roas_total']:.2f}" if data['roas_total'] is not None else '')
    writer.writerow(roas_row)

    for item in data['income']:
        write_currency_row('Income', item['name'], item['periods'], item['total'])
    write_currency_row('Income', 'Total Income', period_totals['income'], sum(period_totals['income'].values()))

    # COGS
    for item in data['cogs']:
        write_currency_row('COGS', item['name'], item['periods'], item['total'])
    write_currency_row('COGS', 'Total COGS', period_totals['cogs'], sum(period_totals['cogs'].values()))

    # Profit summaries
    write_currency_row('Summary', 'Gross Profit', period_totals['gross_profit'], sum(period_totals['gross_profit'].values()))

    # Expenses
    for item in data['expenses']:
        write_currency_row('Expenses', item['name'], item['periods'], item['total'])
    write_currency_row('Expenses', 'Total Expenses', period_totals['expenses'], sum(period_totals['expenses'].values()))
    write_currency_row('Summary', 'Net Profit', period_totals['net_profit'], sum(period_totals['net_profit'].values()))

    filename = f"pl_report_{start_date.isoformat()}_to_{end_date.isoformat()}_{granularity}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )
