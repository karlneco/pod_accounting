import os
import uuid

from flask import Blueprint, render_template, url_for, redirect, flash, request, current_app
from sqlalchemy import func
from io import TextIOWrapper
import csv
from decimal import Decimal
from ..models import db, Order, Customer, OrderItem, Product

bp = Blueprint('orders', __name__, template_folder='templates/orders')


@bp.route('/')
def list_orders():
    # Aggregate order stats
    stats = (
        db.session.query(
            Order.order_number,
            Order.order_date,
            Customer.name.label('customer_name'),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label('order_total'),
            Order.delivery_status
        )
        .join(Customer)
        .outerjoin(OrderItem)
        .group_by(Order.id)
        .order_by(Order.order_date.desc())
        .all()
    )

    total_orders = len(stats)
    total_value = sum(s.order_total for s in stats)

    return render_template(
        'orders/list.html',
        stats=stats,
        total_orders=total_orders,
        total_value=total_value
    )


@bp.route('/new')
def create_order():
    # Placeholder for order creation form
    flash('Order creation not implemented yet', 'info')
    return redirect(url_for('orders.list_orders'))


@bp.route('/import', methods=['GET', 'POST'])
def import_orders():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('No file selected', 'warning')
            return redirect(url_for('orders.import_orders'))

        upload_dir = os.path.join(current_app.root_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)

        # generate a unique filename
        file_key = f"{uuid.uuid4().hex}.csv"
        file_path = os.path.join(upload_dir, file_key)

        # persist the upload
        file.save(file_path)

        # Load existing DB state to avoid duplicates
        existing_customers = {c.email for c in Customer.query.with_entities(Customer.email).all()}
        existing_products = {p.name for p in Product.query.with_entities(Product.name).all()}
        existing_orders = {o.order_number: o for o in Order.query.with_entities(Order).all()}

        # Prepare data structures for new entries only
        customers_to_create = {}
        products_to_create = {}
        order_currencies = {}
        orders_data = {}
        current_order = None

        # Parse CSV
        stream = TextIOWrapper(file.stream, encoding='utf-8-sig')
        reader = csv.DictReader(stream)
        for row in reader:
            order_num_raw = row.get('Name', '').strip()
            customer_email = row.get('Email', '').strip()
            financial_status = row.get('Financial Status', '').strip()
            order_currency = row.get('Currency').strip() or '???'

            # Identify new order row by presence of financial status
            if order_num_raw and financial_status:
                order_number = order_num_raw.lstrip('#')
                delivery_status = row.get('Fulfillment Status', '').strip() or 'pending'
                order_currencies[order_number] = order_currency

                # If order exists, update status and skip import
                if order_number in existing_orders:
                    existing_order = existing_orders[order_number]
                    if existing_order.delivery_status != delivery_status:
                        existing_order.delivery_status = delivery_status
                        db.session.add(existing_order)
                    # Skip further processing for this order
                    current_order = None
                    continue

                # Else, queue new order for preview
                order_date = row.get('Created at', '').split(' ')[0]
                total_str = row.get('Total', '').strip() or '0'
                order_discount_amount_str = row.get('Discount Amount').strip() or 0
                order_sub_total_str = row.get('Subtotal').strip() or 0
                order_shipping_str = row.get('Shipping').strip() or 0
                order_taxes_str = row.get('Taxes').strip() or 0
                order_total = Decimal(total_str)
                order_discount_amount = Decimal(order_discount_amount_str)
                order_sub_total = Decimal(order_sub_total_str)
                order_shipping = Decimal(order_shipping_str)
                order_taxes = Decimal(order_taxes_str)

                # Queue customer creation if missing
                if customer_email and customer_email not in existing_customers and customer_email not in customers_to_create:
                    c_name = row.get('Billing Name', '').strip()
                    c_phone = row.get('Billing Phone', '').strip() or row.get('Phone', '').strip()
                    addr_parts = [
                        row.get('Billing Address1', '').strip(),
                        row.get('Billing Address2', '').strip(),
                        row.get('Billing City', '').strip(),
                        row.get('Billing Province', '').strip(),
                        row.get('Billing Zip', '').strip(),
                        row.get('Billing Country', '').strip()
                    ]
                    c_address = ', '.join(p for p in addr_parts if p)
                    customers_to_create[customer_email] = {
                        'name': c_name,
                        'email': customer_email,
                        'phone': c_phone,
                        'address': c_address
                    }

                # Initialize order entry for preview
                orders_data[order_number] = {
                    'order_number': order_number,
                    'customer_email': customer_email,
                    'order_date': order_date,
                    'delivery_status': delivery_status,
                    'discount_amount': order_discount_amount,
                    'sub_total': order_sub_total,
                    'shipping': order_shipping,
                    'taxes': order_taxes,
                    'order_total': order_total,
                    'items': []
                }
                current_order = order_number

            # Handle line items for new orders
            line_name = row.get('Lineitem name', '').strip()
            if line_name and current_order:
                parts = line_name.rsplit(' - ', 1)
                base_name = parts[0]
                variant = parts[1] if len(parts) > 1 else ''
                price_str = row.get('Lineitem price', '').strip() or '0'
                sku = row.get('Lineitem sku', '').strip() or '0'
                quantity_str = row.get('Lineitem quantity', '').strip() or '0'
                price = Decimal(price_str)
                quantity = int(quantity_str)


                # Queue product creation if missing
                if base_name and base_name not in existing_products and base_name not in products_to_create:
                    products_to_create[base_name] = {'name': base_name, 'price': price}

                orders_data[current_order]['items'].append({
                    'name': base_name,
                    'product_sku': sku,
                    'variant': variant,
                    'quantity': quantity,
                    'unit_price': price,
                    'order_currency': order_currencies[current_order],
                })

        # Commit any status updates
        db.session.commit()

        # Render verify page for new entries only
        return render_template(
            'orders/verify.html',
            customers=customers_to_create,
            products=products_to_create,
            orders=orders_data
        )

    # GET: show upload form
    return render_template('orders/import.html')


@bp.route('/import/confirm', methods=['POST'])
def confirm_import():
    file_key = request.form.get('file_key')
    if not file_key:
        flash('No import in progress.', 'warning')
        return redirect(url_for('orders.import_orders'))

    # Reconstruct the file path
    import os
    upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'uploads'))
    filepath   = os.path.join(upload_dir, file_key)
    if not os.path.exists(filepath):
        flash('Import session expired. Please re-upload.', 'warning')
        return redirect(url_for('orders.import_orders'))

    # Now re-run your “perform_import” logic here:
    #   - parse the CSV again
    #   - create customers, products, orders & items
    #   - commit to DB
    count = perform_import(filepath)   # you’ll need to extract and reuse your import code

    # Clean up the temp file
    os.remove(filepath)

    flash(f'Successfully imported {count} new orders!', 'success')
    return redirect(url_for('orders.list_orders'))
