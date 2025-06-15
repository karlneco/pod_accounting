# app/importers/printify.py

import csv
import re
from datetime import datetime
from decimal import Decimal

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
          {'description': str, 'amount': Decimal},
          ...
        ]
    """
    invoices = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 1) invoice date
            created = row.get('Date created', '').strip()
            inv_date = (
                datetime.fromisoformat(created).date()
                if created else None
            )

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
                {'description': 'Production Cost', 'amount': product_cost},
                {'description': 'Shipping Cost', 'amount': ship_cost},
                {'description': 'Sales Tax Charged', 'amount': tax_cost},
            ]

            invoices.append({
                'provider_id': provider_id,
                'invoice_date': inv_date,
                'invoice_number': sales_chan_num,
                'supplier_invoice': printify_inv_no,
                'total_amount': total_cost,
                'items': items
            })

    return invoices, []
