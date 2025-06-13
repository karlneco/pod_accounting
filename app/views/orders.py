from flask import Blueprint, render_template, url_for, redirect, flash
from sqlalchemy import func
from ..models import db, Order, Customer, OrderItem

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


@bp.route('/import')
def import_orders():
    # Placeholder for order import
    flash('Order import not implemented yet', 'info')
    return redirect(url_for('orders.list_orders'))
