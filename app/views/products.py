from flask import Blueprint, render_template, url_for, redirect, flash
from sqlalchemy import func
from ..models import db, Product, OrderItem

bp = Blueprint('products', __name__, template_folder='templates/products')

@bp.route('/')
def list_products():
    # For each product, sum up quantities sold (0 if none)
    stats = (
        db.session.query(
            Product,
            func.coalesce(func.sum(OrderItem.quantity), 0).label('items_sold')
        )
        .outerjoin(OrderItem)
        .group_by(Product.id)
        .order_by(func.coalesce(func.sum(OrderItem.quantity), 0).desc())
        .all()
    )
    total_products = len(stats)
    return render_template(
        'products/list.html',
        stats=stats,
        total_products=total_products
    )

@bp.route('/new')
def create_product():
    flash('Product creation not implemented yet', 'info')
    return redirect(url_for('products.list_products'))

@bp.route('/import')
def import_products():
    flash('Product import not implemented yet', 'info')
    return redirect(url_for('products.list_products'))