# app/importers/meta_ads.py

import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from ..models import db, ExpenseInvoice, ExpenseItem, Account, Provider


def parse(filepath, provider_id):
    """
    Parse a Meta daily-spend CSV into a list of invoice dicts,
    each with an 'action' of:
      - 'skip'   : already exists with same total_amount
      - 'update' : exists but total_amount (or GST) changed
      - 'create' : new invoice
    """
    invoices = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        # 6) lookup GST account
        gst_acct = Account.query.filter_by(name='GST Paid').first()
        gst_acct_id = gst_acct.id if gst_acct else None
        provider = Provider.query.get_or_404(provider_id)
        default_ad_account = provider.default_account_id

        for row in reader:
            # --- build the invoice dict (date, number, items) ---
            day = row.get('Day','').strip()
            try:
                inv_date = datetime.fromisoformat(day).date()
            except Exception:
                inv_date = None

            invoice_number = (
                f"MTAD-{inv_date.strftime('%Y%m%d')}"
                if inv_date else
                "MTAD-unknown"
            )

            raw = row.get('Amount spent (CAD)', '0').strip() or '0'
            try:
                net = Decimal(raw)
            except Exception:
                net = Decimal('0')

            gst = (net * Decimal('0.05')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total = net + gst

            # --- check DB for existing invoice ---
            existing = ExpenseInvoice.query.filter_by(
                provider_id=provider_id,
                invoice_number=invoice_number
            ).first()

            if existing:
                if existing.total_amount == total:
                    action = 'skip'
                else:
                    action = 'update'
            else:
                action = 'create'

            invoices.append({
                'provider_id':     provider_id,
                'invoice_date':    inv_date,
                'invoice_number':  invoice_number,
                'supplier_invoice': None,
                'total_amount':    total,
                'items': [
                    {'description': 'Daily Ad Spend', 'amount': net, 'account_id': default_ad_account},
                    {'description': 'GST',             'amount': gst, 'account_id': gst_acct_id},
                ],
                'action':          action,
                'existing_id':     existing.id if existing else None
            })
    return invoices, []
