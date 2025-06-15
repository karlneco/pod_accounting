from flask import Blueprint, render_template, url_for, redirect, flash, request
from ..models import Account, db

bp = Blueprint('accounts', __name__, template_folder='templates/accounts')

@bp.route('/')
def list_accounts():
    """Show all accounts."""
    accounts = Account.query.order_by(Account.id).all()
    return render_template('accounts/list.html', accounts=accounts)

@bp.route('/new', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        name  = request.form.get('name')
        type_ = request.form.get('type')
        if not name or not type_:
            flash('Name and Type are required.', 'warning')
            return redirect(url_for('accounts.create_account'))

        existing = Account.query.filter_by(name=name).first()
        if existing:
            flash(f"Account '{name}' already exists.", 'warning')
            return redirect(url_for('accounts.list_accounts'))

        acct = Account(name=name, type=type_)
        db.session.add(acct)
        db.session.commit()
        flash(f"Account '{name}' created.", 'success')
        return redirect(url_for('accounts.list_accounts'))

    # GET: render the new account form
    return render_template('accounts/new.html')
