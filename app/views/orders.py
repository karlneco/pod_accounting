import os
import uuid
import csv
from datetime import date
from decimal import Decimal
from flask import (
    Blueprint, render_template, url_for, redirect,
    flash, request, current_app
)
from sqlalchemy import func
from ..models import db, Order, Customer, OrderItem, Product, Account

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
    existing_orders = {o.order_number for o in Order.query.with_entities(Order.order_number)}

    customers_to_create = {}
    products_to_create = {}
    orders_data = {}
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
                # skip existing orders
                if num in existing_orders:
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
                    'delivery_status': row.get('Fulfillment Status', '').strip() or 'pending',
                    'sub_total': Decimal(row.get('Subtotal', '0').strip() or 0),
                    'shipping': Decimal(row.get('Shipping', '0').strip() or 0),
                    'taxes': Decimal(row.get('Taxes', '0').strip() or 0),
                    'order_total': Decimal(row.get('Total', '0').strip() or 0),
                    'discount_amount': Decimal(row.get('Discount Amount', '0').strip() or 0),
                    'items': [],
                    'order_currency': order_currency
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

    return customers_to_create, products_to_create, orders_data


def perform_import(filepath):
    """
    Parses and writes to DB: creates customers, products, orders, order items.
    Returns number of orders created.
    """
    customers_to_create, products_to_create, orders_data = parse_orders_csv(filepath)

    # create customers
    email_map = {}
    for email, data in customers_to_create.items():
        customer = Customer.query.filter_by(email=email).first()
        if not customer:
            customer = Customer(**data)
            db.session.add(customer)
        email_map[email] = customer
    db.session.commit()

    # create products
    name_map = {}
    for name, data in products_to_create.items():
        product = Product.query.filter_by(name=name).first()
        if not product:
            product = Product(name=data['name'], price=data['price'])
            db.session.add(product)
        name_map[name] = product
    db.session.commit()

    # select default income account for order items
    income_acc = Account.query.filter_by(type='Income').first()
    default_acc_id = income_acc.id if income_acc else None

    # create orders + items
    created_count = 0
    for num, od in orders_data.items():
        cust = Customer.query.filter_by(email=od['customer_email']).first() or email_map.get(od['customer_email'])
        order = Order(
            order_number=od['order_number'],
            customer_id=cust.id,
            order_date=od['order_date'],
            total_amount=od['order_total'],
            sub_total=od['sub_total'],
            taxes=od['taxes'],
            shipping=od['shipping'],
            discount_amount=od['discount_amount'],
            delivery_status=od['delivery_status']
        )
        db.session.add(order)
        db.session.flush()

        for it in od['items']:
            prod = Product.query.filter_by(name=it['name']).first() or name_map.get(it['name'])
            subtotal = it['unit_price'] * it['quantity']
            order_item = OrderItem(
                order_id=order.id,
                product_id=prod.id if prod else None,
                product_sku=it['product_sku'],
                variant=it.get('variant'),
                quantity=it['quantity'],
                unit_price=it['unit_price'],
                currency_code=it['currency_code'],
                subtotal=subtotal,
                account_id=default_acc_id
            )
            db.session.add(order_item)

        created_count += 1

    db.session.commit()
    return created_count


@bp.route('/')
def list_orders():
    stats = (
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
        .order_by(Order.order_date.desc())
        .all()
    )
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
        customers, products, orders = parse_orders_csv(file_path)

        return render_template(
            'orders/verify.html',
            file_key=file_key,
            customers=customers,
            products=products,
            orders=orders
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

    # order.items is already available via the relationship
    return render_template(
        'orders/detail.html',
        order=order
    )
