import csv
import re
from datetime import datetime
from decimal import Decimal

from app.models import Account, ExpenseInvoice

# helper to pull the numeric part out of strings like “9.73 USD” or “1,234.56 USD”
_amount_re = re.compile(r'-?\d[\d,]*\.?\d*')


def _clean_amount(raw: str) -> Decimal:
    raw = (raw or '').strip()
    m = _amount_re.search(raw)
    if not m:
        return Decimal('0')
    # strip commas, leave the digits and dot
    num = m.group(0).replace(',', '')
    try:
        return Decimal(num)
    except Exception:
        return Decimal('0')


def parse(filepath, provider_id):
    """
    Parses a Printify CSV into a list of invoice dicts:
      - provider_id
      - invoice_date
      - invoice_number  (Sales Channel Number)
      - supplier_invoice (Printify’s own Invoice #)
      - total_amount
      - items: [
          {'description': str, 'amount': Decimal, 'account_id': int, 'currency_code': str},
          ...
        ]
      - action (‘create’, ‘update’, or ‘skip’)
      - existing_id (ExpenseInvoice.id if updating)
    Returns (invoices, missing).
    """
    invoices = []
    missing = []  # no missing-payee logic here, but keep interface

    # preload existing invoices for this provider
    existing = {
        inv.invoice_number: inv
        for inv in ExpenseInvoice.query.filter_by(provider_id=provider_id).all()
    }

    # lookup the 3 COGS accounts
    product_sale_acc_id = Account.query.filter_by(name='COGS').first().id
    cust_shipping_acc_id = Account.query.filter_by(name='COGS Shipping').first().id
    sales_tax_charged_acc_id = Account.query.filter_by(name='COGS Tax').first().id

    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 1) invoice date
            created = row.get('Date created', '').strip()
            try:
                inv_date = datetime.fromisoformat(created).date()
            except Exception:
                inv_date = None

            # 2) Sales Channel Number + Printify Invoice #
            sales_chan_num = row.get('Sales channel Number', '').strip().lstrip('#')
            printify_inv_no = row.get('Invoices', '').strip()

            # 3) clean amounts
            total_cost = _clean_amount(row.get('Total cost'))
            product_cost = _clean_amount(row.get('Product Cost'))
            ship_cost = _clean_amount(row.get('Shipping Cost'))
            tax_cost = _clean_amount(row.get('VAT / Tax cost'))

            # 4) build exactly three line-items
            items = [
                {
                    'description': 'Production Cost',
                    'amount': product_cost,
                    'account_id': product_sale_acc_id,
                    'currency_code': 'USD'
                },
                {
                    'description': 'Shipping Cost',
                    'amount': ship_cost,
                    'account_id': cust_shipping_acc_id,
                    'currency_code': 'USD'
                },
                {
                    'description': 'Sales Tax Charged',
                    'amount': tax_cost,
                    'account_id': sales_tax_charged_acc_id,
                    'currency_code': 'USD'
                },
            ]

            # 5) decide action based on existing invoice
            exist = existing.get(sales_chan_num)
            if exist:
                action = 'skip' if exist.total_amount == total_cost else 'update'
                existing_id = exist.id
            else:
                action = 'create'
                existing_id = None

            invoices.append({
                'provider_id': provider_id,
                'invoice_date': inv_date,
                'invoice_number': sales_chan_num,
                'supplier_invoice': printify_inv_no,
                'total_amount': total_cost,
                'items': items,
                'action': action,
                'existing_id': existing_id
            })

    return invoices, missing
