# app/importers/generic.py

import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from ..models import Provider, Account, ExpenseInvoice


def parse(filepath, provider_id):
    """
    Parse a generic expenses CSV into invoice dicts with:
      - provider_id, invoice_date, invoice_number, supplier_invoice, total_amount
      - items: list of {description, amount, account_id, currency_code}
      - action: 'create' | 'update' | 'skip'
      - existing_id: ExpenseInvoice.id if updating
    """
    invoices = []
    missing = set()

    # preload existing invoices for all providers as this is a generic import
    existing = {
        inv.invoice_number: inv
        for inv in ExpenseInvoice.query
        .all()
    }

    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            # 1) parse the date (DD/MM/YYYY)
            try:
                inv_date = datetime.strptime(row['Date'], '%d/%m/%Y').date()
            except Exception:
                inv_date = None

            # 2) lookup provider by Payee (case‐insensitive contains)
            payee = row.get('Payee', '').strip()
            prov = Provider.query \
                .filter(Provider.name.ilike(f"%{payee}%")) \
                .first()
            if not prov:
                # record missing and skip this row entirely
                missing.add(payee or f"<blank row {idx}>")
                continue
            pid = prov.id

            # 3) generate a stable invoice_number
            if inv_date:
                date_str = inv_date.strftime('%Y%m%d')
            else:
                # fallback to just row number if date bad
                date_str = f"row{idx}"
            invoice_number = f"GEN-{pid}-{date_str}-{idx}"

            # 4) parse amounts
            raw_net = (row.get('Total before sales tax') or '0').strip()
            raw_tax = (row.get('Sales tax') or '0').strip()
            raw_tot = (row.get('Total') or '0').strip()
            try:
                net = Decimal(raw_net)
            except:
                net = Decimal('0')
            try:
                tax = Decimal(raw_tax)
            except:
                tax = Decimal('0')
            try:
                total = Decimal(raw_tot)
            except:
                total = Decimal('0')

            # currency: CAD if there is a tax, else USD
            currency = 'CAD' if tax != 0 else 'USD'

            # 5) lookup the expense account by Category
            category = row.get('Category', '').strip()
            acct = Account.query.filter_by(name=category).first()
            acct_id = acct.id if acct else None

            # 6) lookup GST account
            gst_acct = Account.query.filter_by(name='GST Paid').first()
            gst_acct_id = gst_acct.id if gst_acct else None

            # 7) build items
            items = [
                {
                    'description': category,
                    'amount': net,
                    'account_id': acct_id,
                    'currency_code': currency
                }
            ]
            if tax != 0:
                items.append({
                    'description': 'Sales Tax',
                    'amount': tax,
                    'account_id': gst_acct_id,
                    'currency_code': currency
                })

            # 8) decide action based on existing total_amount
            existing_inv = existing.get(invoice_number)
            if existing_inv:
                action = 'skip' if existing_inv.total_amount == total else 'update'
            else:
                action = 'create'

            invoices.append({
                'provider_id': pid,
                'invoice_date': inv_date,
                'invoice_number': invoice_number,
                'supplier_invoice': None,
                'total_amount': total,
                'items': items,
                'action': action,
                'existing_id': existing_inv.id if existing_inv else None
            })

    return invoices, sorted(missing)
