from flask import Blueprint, render_template, url_for, redirect, flash
from sqlalchemy import func
from ..models import db, Customer, Order

bp = Blueprint('customers', __name__, template_folder='templates/customers')

@bp.route('/')
def list_customers():
    # Aggregate order stats per customer
    stats = db.session.query(
        Customer,
        func.count(Order.id).label('order_count'),
        func.max(Order.order_date).label('last_order_date'),
        func.coalesce(func.sum(Order.total_amount), 0).label('amount_spent')
    ).outerjoin(Order).group_by(Customer.id).all()

    total_customers = len(stats)
    total_spent = sum(stat.amount_spent for stat in stats)

    return render_template(
        'customers/list.html',
        stats=stats,
        total_customers=total_customers,
        total_spent=total_spent
    )

@bp.route('/new')
def create_customer():
    # Placeholder for customer creation form
    flash('Customer creation not implemented yet', 'info')
    return redirect(url_for('customers.list_customers'))

@bp.route('/import')
def import_customers():
    # Placeholder for customer import
    flash('Customer import not implemented yet', 'info')
    return redirect(url_for('customers.list_customers'))