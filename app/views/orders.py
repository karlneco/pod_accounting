import csv
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

from flask import (
    Blueprint, render_template, url_for, redirect,
    flash, request, current_app
)

from ..models import db, Order, Customer, OrderItem, Product, Account, ExpenseItem, Provider, ExpenseInvoice
from ..utils.currency import usd_to_cad
from ..utils.date_filters import get_date_range

bp = Blueprint('orders', __name__, template_folder='templates/orders')


def parse_orders_csv(filepath):
    """
    Parses the CSV at filepath and returns three dicts:
      - customers_to_create: {email: {name,email,phone,address}}
      - products_to_create:  {product_name: {name,price}}
      - orders_data:         {order_number: {order fields + items list}}
    Skips any existing orders (by order_number).
    """
    existing_customers = {c.email for c in Customer.query.with_entities(Customer.email)}
    existing_products = {p.name for p in Product.query.with_entities(Product.name)}
    existing_orders = {
        o.order_number: o.delivery_status
        for o in Order.query.with_entities(Order.order_number, Order.delivery_status)
    }

    customers_to_create = {}
    products_to_create = {}
    orders_data = {}
    updates_data = {}
    current_order = None

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            order_key = row.get('Name', '').strip()
            financial_status = row.get('Financial Status', '').strip()
            order_currency = row.get('Currency', '').strip()

            # start of new order
            if order_key and financial_status:
                num = order_key.lstrip('#')
                raw_pm = row.get('Payment Method', '').lower()
                if 'shopify' in raw_pm:
                    pm = 'shopify'
                elif 'paypal' in raw_pm:
                    pm = 'paypal'
                else:
                    pm = None

                new_status = row.get('Fulfillment Status', '').strip() or 'unfulfilled'
                # existing order → track status change, then skip
                if num in existing_orders:
                    if existing_orders[num] != new_status:
                        updates_data[num] = {
                            'order_number': num,
                            'new_status': new_status
                        }
                    current_order = None
                    continue

                created_at = row.get('Created at', '').strip()
                if created_at:
                    date_str = created_at.split(' ')[0]
                    try:
                        order_date = date.fromisoformat(date_str)
                    except ValueError:
                        order_date = None
                else:
                    order_date = None

                # initialize new order
                orders_data[num] = {
                    'order_number': num,
                    'customer_email': row.get('Email', '').strip(),
                    'order_date': order_date,
                    'delivery_status': new_status,
                    'sub_total': Decimal(row.get('Subtotal', '0').strip() or 0),
                    'shipping': Decimal(row.get('Shipping', '0').strip() or 0),
                    'taxes': Decimal(row.get('Taxes', '0').strip() or 0),
                    'order_total': Decimal(row.get('Total', '0').strip() or 0),
                    'discount_amount': Decimal(row.get('Discount Amount', '0').strip() or 0),
                    'items': [],
                    'order_currency': order_currency,
                    'payment_method': pm
                }
                current_order = num

                # queue new customer
                email = row.get('Email', '').strip()
                if email and email not in existing_customers and email not in customers_to_create:
                    customers_to_create[email] = {
                        'name': row.get('Billing Name', '').strip(),
                        'email': email,
                        'phone': row.get('Billing Phone', '').strip() or row.get('Phone', '').strip(),
                        'address': ', '.join(
                            p for p in [
                                row.get('Billing Address1', '').strip(),
                                row.get('Billing City', '').strip(),
                                row.get('Billing Province', '').strip(),
                                row.get('Billing Zip', '').strip(),
                                row.get('Billing Country', '').strip()
                            ] if p
                        )
                    }

            # line items for the current order
            name = row.get('Lineitem name', '').strip()
            if name and current_order:
                parts = name.rsplit(' - ', 1)
                base = parts[0]
                var = parts[1] if len(parts) > 1 else None
                price = Decimal(row.get('Lineitem price', '0').strip() or 0)
                qty = int(row.get('Lineitem quantity', '0').strip() or 0)
                sku = row.get('Lineitem sku', '').strip()

                # queue new product
                if base not in existing_products and base not in products_to_create:
                    products_to_create[base] = {'name': base, 'price': price}

                orders_data[current_order]['items'].append({
                    'name': base,
                    'variant': var,
                    'product_sku': sku,
                    'quantity': qty,
                    'currency_code': orders_data[current_order]['order_currency'],
                    'unit_price': price
                })

    return customers_to_create, products_to_create, orders_data, updates_data


def perform_import(filepath):
    """
    Parses and writes to DB: creates customers, products, orders, order items,
    plus shipping & discount line‐items in dedicated accounts.
    Returns number of orders created.
    """
    customers_to_create, products_to_create, orders_data, updates_data = parse_orders_csv(filepath)

    # --- create customers ---
    email_map = {}
    for email, data in customers_to_create.items():
        customer = Customer.query.filter_by(email=email).first()
        if not customer:
            customer = Customer(**data)
            db.session.add(customer)
        email_map[email] = customer
    db.session.commit()

    # --- create products ---
    name_map = {}
    for name, data in products_to_create.items():
        product = Product.query.filter_by(name=name).first()
        if not product:
            product = Product(name=data['name'], price=data['price'])
            db.session.add(product)
        name_map[name] = product
    db.session.commit()

    # --- look up accounts ---
    income_acc = Account.query.filter_by(type='Income').first()
    default_acc_id = income_acc.id if income_acc else None

    ship_acc = Account.query.filter_by(name='Shipping Charged').first()
    ship_acc_id = ship_acc.id if ship_acc else default_acc_id

    disc_acc = Account.query.filter_by(name='Discounts Given').first()
    disc_acc_id = disc_acc.id if disc_acc else default_acc_id

    merchant_acc = Account.query.filter_by(name='Merchant Fees').first()
    merchant_acc_id = merchant_acc.id if merchant_acc else default_acc_id

    conv_acc = Account.query.filter_by(name='Currency Conversion Fees').first()
    conv_acc_id = conv_acc.id if conv_acc else default_acc_id

    created_count = 0

    # pick a currency code for fees (we store fees in CAD)
    fee_currency = 'CAD'

    # --- create orders + items ---
    for num, od in orders_data.items():
        # customer lookup
        cust = Customer.query.filter_by(email=od['customer_email']).first() \
               or email_map.get(od['customer_email'])

        # create Order header
        order = Order(
            order_number=od['order_number'],
            customer_id=cust.id,
            order_date=od['order_date'],
            total_amount=od['order_total'],
            sub_total=od.get('sub_total'),
            shipping=od.get('shipping'),
            taxes=od.get('taxes'),
            discount_amount=od.get('discount_amount'),
            delivery_status=od['delivery_status'],
            payment_method=od['payment_method']
        )
        db.session.add(order)
        db.session.flush()  # so order.id is assigned

        # grab a currency_code from the first line (fallback to None)
        first_currency = None
        if od['items']:
            first_currency = od['items'][0].get('currency_code')

        # 1) product line items
        for it in od['items']:
            prod = Product.query.filter_by(name=it['name']).first() \
                   or name_map.get(it['name'])
            subtotal = it['unit_price'] * it['quantity']
            order_item = OrderItem(
                order_id=order.id,
                product_id=prod.id if prod else None,
                product_sku=it['product_sku'],
                variant=it.get('variant'),
                quantity=it['quantity'],
                unit_price=it['unit_price'],
                subtotal=subtotal,
                currency_code=it.get('currency_code') or first_currency,
                account_id=default_acc_id
            )
            db.session.add(order_item)

        # 2) shipping line (positive amount)
        ship_amt = od.get('shipping') or Decimal('0')
        if ship_amt and ship_amt != 0:
            ship_item = OrderItem(
                order_id=order.id,
                product_id=None,
                product_sku='SHIPPING',
                variant=None,
                quantity=1,
                unit_price=ship_amt,
                subtotal=ship_amt,
                currency_code=first_currency,
                account_id=ship_acc_id
            )
            db.session.add(ship_item)

        # 3) discount line (negative amount)
        disc_amt = od.get('discount_amount') or Decimal('0')
        if disc_amt and disc_amt != 0:
            disc_item = OrderItem(
                order_id=order.id,
                product_id=None,
                product_sku='DISCOUNT',
                variant=None,
                quantity=1,
                unit_price=-disc_amt,
                subtotal=-disc_amt,
                currency_code=first_currency,
                account_id=disc_acc_id
            )
            db.session.add(disc_item)

        if order.payment_method == 'shopify':
            # --- Shopify Payments & Conversion Fees ---
            # 1) convert order total to CAD
            cad_total = usd_to_cad(order.total_amount, order.order_date)

            # 2) Shopify Payments fee: 3.5% of CAD + $0.30
            payment_fee = (cad_total * Decimal('0.035') + Decimal('0.30')) \
                .quantize(Decimal('0.01'))

            # 3) Currency Conversion fee: 2% of payment_fee
            conversion_fee = (cad_total * Decimal('0.02')).quantize(Decimal('0.01'))

            # look up the “Shopify” provider once
            shopify = Provider.query.filter_by(name='Shopify').first()
            if shopify and (payment_fee or conversion_fee):
                total_fees = payment_fee + conversion_fee

                # create an expense‐invoice for Shopify
                exp_inv = ExpenseInvoice(
                    provider_id=shopify.id,
                    invoice_date=order.order_date,
                    invoice_number=order.order_number,  # link to the order
                    supplier_invoice=None,  # you can set if available
                    total_amount=total_fees
                )
                db.session.add(exp_inv)
                db.session.flush()  # get exp_inv.id

                # Merchant Fees line
                db.session.add(ExpenseItem(
                    expense_invoice_id=exp_inv.id,
                    account_id=merchant_acc_id,  # your “Merchant Fees” account
                    description='Shopify Payments Fee',
                    amount=payment_fee,
                    currency_code=shopify.currency_code,
                    order_id=order.order_number
                ))

                # Currency Conversion Fees line
                db.session.add(ExpenseItem(
                    expense_invoice_id=exp_inv.id,
                    account_id=conv_acc_id,  # your “Currency Conversion Fees” account
                    description='Currency Conversion Fee',
                    amount=conversion_fee,
                    currency_code=shopify.currency_code,
                    order_id=order.order_number
                ))

        created_count += 1

    db.session.commit()
    return created_count


@bp.route('/')
def list_orders():
    # read filter params
    range_key = request.args.get('range', 'this_month')
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    start = datetime.fromisoformat(start_str).date() if start_str else None
    end = datetime.fromisoformat(end_str).date() if end_str else None
    start_date, end_date = get_date_range(range_key, start, end)

    q = (
        db.session.query(
            Order.order_number,
            Order.order_date,
            Customer.name.label('customer_name'),
            Order.sub_total.label('subtotal'),
            Order.shipping.label('shipping'),
            Order.total_amount.label('order_total'),
            Order.delivery_status
        )
        .join(Customer)
        .outerjoin(OrderItem)
        .group_by(Order.id)
        .order_by(Order.order_date.desc()))

    if start_date and end_date:
        q = q.filter(Order.order_date.between(start_date, end_date))

    stats = q.all()

    total_orders = len(stats)
    total_sub = sum(s.subtotal for s in stats)
    total_shipping = sum(s.shipping for s in stats)
    total_value = sum(s.order_total for s in stats)
    return render_template(
        'orders/list.html',
        stats=stats,
        total_sub=total_sub,
        total_shipping=total_shipping,
        total_orders=total_orders,
        total_value=total_value
    )


@bp.route('/new')
def create_order():
    flash('Order creation not implemented yet', 'info')
    return redirect(url_for('orders.list_orders'))


@bp.route('/import', methods=['GET', 'POST'])
def import_orders():
    if request.method == 'POST':
        uploaded = request.files.get('file')
        if not uploaded:
            flash('No file selected', 'warning')
            return redirect(url_for('orders.import_orders'))

        # save the uploaded file
        upload_dir = os.path.join(current_app.root_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        file_key = f"{uuid.uuid4().hex}.csv"
        file_path = os.path.join(upload_dir, file_key)
        uploaded.save(file_path)

        # parse CSV for verification
        customers, products, new_orders, updates_data = parse_orders_csv(file_path)

        return render_template(
            'orders/verify.html',
            file_key=file_key,
            customers=customers,
            products=products,
            new_orders=new_orders,
            updates_data=updates_data
        )

    # GET: show upload form
    return render_template('orders/import.html')


@bp.route('/import/confirm', methods=['POST'])
def confirm_import():
    file_key = request.form.get('file_key')
    if not file_key:
        flash('No import in progress.', 'warning')
        return redirect(url_for('orders.import_orders'))

    upload_dir = os.path.join(current_app.root_path, 'uploads')
    file_path = os.path.join(upload_dir, file_key)
    if not os.path.exists(file_path):
        flash('Import session expired. Please re-upload.', 'warning')
        return redirect(url_for('orders.import_orders'))

    created = perform_import(file_path)
    os.remove(file_path)

    flash(f'Successfully imported {created} new orders!', 'success')
    return redirect(url_for('orders.list_orders'))


@bp.route('/<order_number>')
def show_order(order_number):
    # fetch the order (404 if not found)
    order = Order.query.filter_by(order_number=order_number).first_or_404()

    # Fetch any expense‐items linked to this order
    expense_items = ExpenseItem.query.filter_by(order_id=order.order_number).all()

    # 3) Determine order currency from first line‐item (fallback to USD)
    first_item = order.items[0] if order.items else None
    order_currency = getattr(first_item, 'currency_code', 'USD')

    cogs_usd = Decimal('0')
    fees_cad = Decimal('0')

    # 5) Define which accounts count as COGS vs. Fees
    cogs_names = {'COGS', 'COGS Shipping', 'COGS Tax'}
    fee_names = {'Merchant Fees', 'Currency Conversion Fees'}

    # 6) Sum up each expense‐item into COGS or Fees, converting to CAD
    for exp in expense_items:
        amt = exp.amount or Decimal('0')
        acct_name = exp.account.name if exp.account else None
        if acct_name in cogs_names:
            cogs_usd += amt
        elif acct_name in fee_names:
            fees_cad += amt

    # compute COGS, Profit and Margin
    revenue_cad = usd_to_cad(order.total_amount, order.order_date)
    profit_cad = revenue_cad - usd_to_cad(cogs_usd, order.order_date) - fees_cad

    if order.total_amount and order.total_amount != 0:
        margin = (profit_cad / revenue_cad * Decimal('100')).quantize(Decimal('0.01'))
    else:
        margin = None

    return render_template(
        'orders/detail.html',
        order=order,
        expense_items=expense_items,
        cogs_usd=cogs_usd,
        fees_cad=fees_cad,
        profit_cad=profit_cad,
        margin=margin
    )
