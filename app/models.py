from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# define naming patterns
naming_convention = {
    "ix":  "ix_%(column_0_label)s",
    "uq":  "uq_%(table_name)s_%(column_0_name)s",
    "ck":  "ck_%(table_name)s_%(constraint_name)s",
    "fk":  "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk":  "pk_%(table_name)s"
}

# pass it into the metadata used by SQLAlchemy
metadata = MetaData(naming_convention=naming_convention)

db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), unique=True)
    phone = db.Column(db.String(32))
    address = db.Column(db.String(256))
    notes = db.Column(db.Text)

    orders = db.relationship('Order', back_populates='customer', cascade='all, delete-orphan')


class Provider(db.Model):
    __tablename__ = 'providers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    type = db.Column(
        db.Enum('print', 'software', 'other', name='provider_types'),
        nullable=False
    )
    contact_info = db.Column(db.Text)
    notes = db.Column(db.Text)

    expense_invoices = db.relationship('ExpenseInvoice', back_populates='provider', cascade='all, delete-orphan')


class Currency(db.Model):
    __tablename__ = 'currencies'
    code = db.Column(db.String(3), primary_key=True)  # ISO 4217, e.g. 'CAD', 'USD'
    name = db.Column(db.String(64), nullable=False)

    exchange_rates = db.relationship('ExchangeRate', back_populates='currency', cascade='all, delete-orphan')


class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'
    id = db.Column(db.Integer, primary_key=True)
    currency_code = db.Column(db.String(3), db.ForeignKey('currencies.code'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    rate = db.Column(db.Numeric(18, 8), nullable=False)  # Rate relative to base currency

    currency = db.relationship('Currency', back_populates='exchange_rates')


class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    type = db.Column(
        db.Enum('Income', 'COGS', 'Expense', 'Other', name='account_types'),
        nullable=False
    )
    parent_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    description = db.Column(db.Text)

    parent = db.relationship('Account', remote_side=[id], backref='children')


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(12, 2))  # optional retail price

    items = db.relationship('OrderItem', back_populates='product')


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(64), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    order_date = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(12, 2), default=0)
    discount_percent = db.Column(db.Numeric(5, 2), default=0)  # 0–100%
    delivery_status = db.Column(
        db.Enum('pending', 'processing', 'shipped', 'delivered', 'cancelled', name='delivery_statuses'),
        nullable=False,
        default='pending'
    )
    notes = db.Column(db.Text)

    customer = db.relationship('Customer', back_populates='orders')
    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')


class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_sku = db.Column(db.String(64), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    currency_code = db.Column(db.String(3), db.ForeignKey('currencies.code'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)

    order = db.relationship('Order', back_populates='items')
    product = db.relationship('Product', back_populates='items')
    currency = db.relationship('Currency')
    account = db.relationship('Account')


class ExpenseInvoice(db.Model):
    __tablename__ = 'expense_invoices'
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False)
    invoice_number = db.Column(db.String(64))
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    notes = db.Column(db.Text)

    provider = db.relationship('Provider', back_populates='expense_invoices')
    items = db.relationship('ExpenseItem', back_populates='invoice', cascade='all, delete-orphan')


class ExpenseItem(db.Model):
    __tablename__ = 'expense_items'
    id = db.Column(db.Integer, primary_key=True)
    expense_invoice_id = db.Column(db.Integer, db.ForeignKey('expense_invoices.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    description = db.Column(db.String(256))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency_code = db.Column(db.String(3), db.ForeignKey('currencies.code'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)

    invoice = db.relationship('ExpenseInvoice', back_populates='items')
    account = db.relationship('Account')
    currency = db.relationship('Currency')
    order = db.relationship('Order')
