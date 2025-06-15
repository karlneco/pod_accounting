import os

from flask import render_template, redirect, url_for, flash, request, Blueprint, current_app

from app.models import Provider, db, Currency, Account

bp = Blueprint('providers', __name__, template_folder='templates/providers')


@bp.route('/')
def list_providers():
    """List all providers."""
    providers = Provider.query.order_by(Provider.id).all()
    return render_template('providers/list.html', providers=providers)


@bp.route('/new', methods=['GET', 'POST'])
def create_provider():
    # Load currency choices
    currencies = Currency.query.order_by(Currency.code).all()
    accounts = Account.query.order_by(Account.name).all()

    importers_dir = os.path.join(current_app.root_path, 'importers')
    try:
        files = os.listdir(importers_dir)
    except FileNotFoundError:
        files = []
    # take *.py except __init__.py
    importers = sorted(
        os.path.splitext(f)[0]
        for f in files
        if f.endswith('.py') and f != '__init__.py'
    )

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        type_ = request.form.get('type')
        currency_code = request.form.get('currency_code')
        contact_info = request.form.get('contact_info', '').strip()
        notes = request.form.get('notes', '').strip()
        importer_key = request.form.get('importer') or None
        default_account_id = request.form.get('default_account_id', type=int)

        if not name or not type_ or not currency_code:
            flash('Name, Type, and Currency are required.', 'warning')
            return render_template(
                'providers/new.html',
                name=name,
                type=type_,
                currency_code=currency_code,
                contact_info=contact_info,
                notes=notes,
                currencies=currencies,
                importer=importer_key,
                accounts=accounts
            )

        if Provider.query.filter_by(name=name).first():
            flash(f'Provider "{name}" already exists.', 'warning')
            return redirect(url_for('providers.list_providers'))

        p = Provider(
            name=name,
            type=type_,
            currency_code=currency_code,
            importer=importer_key,  # store filename (without .py) or None
            contact_info=contact_info,
            notes=notes,
            default_account_id=default_account_id
        )
        db.session.add(p)
        db.session.commit()

        flash(f'Provider "{name}" created successfully.', 'success')
        return redirect(url_for('providers.list_providers'))

    # GET: render empty form
    return render_template(
        'providers/new.html',
        name='',
        type=None,
        currency_code=None,
        importer=None,
        contact_info='',
        notes='',
        currencies=currencies,
        importers=importers,
        accounts=accounts,
    )


@bp.route('/<int:provider_id>', methods=['GET', 'POST'])
def edit_provider(provider_id):
    provider = Provider.query.get_or_404(provider_id)

    # Load currency choices
    currencies = Currency.query.order_by(Currency.code).all()

    # Dynamically list importer files in app/importers/
    importers_dir = os.path.join(current_app.root_path, 'importers')
    try:
        files = os.listdir(importers_dir)
    except FileNotFoundError:
        files = []
    importers = sorted(
        os.path.splitext(f)[0]
        for f in files
        if f.endswith('.py') and f != '__init__.py'
    )

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        type_ = request.form.get('type')
        currency_code = request.form.get('currency_code')
        importer_key = request.form.get('importer') or None
        contact_info = request.form.get('contact_info', '').strip()
        notes = request.form.get('notes', '').strip()

        if not name or not type_ or not currency_code:
            flash('Name, Type, and Currency are required.', 'warning')
            return render_template(
                'providers/edit.html',
                provider=provider,
                currencies=currencies,
                importers=importers
            )

        # Prevent duplicate names on other records
        existing = Provider.query.filter(
            Provider.name == name,
            Provider.id != provider_id
        ).first()
        if existing:
            flash(f'Provider "{name}" already exists.', 'warning')
            return redirect(url_for('providers.list_providers'))

        # Apply updates
        provider.name = name
        provider.type = type_
        provider.currency_code = currency_code
        provider.importer = importer_key
        provider.contact_info = contact_info
        provider.notes = notes
        db.session.commit()

        flash(f'Provider "{provider.name}" updated.', 'success')
        return redirect(url_for('providers.list_providers'))

    # GET: render form pre-filled
    return render_template(
        'providers/edit.html',
        provider=provider,
        currencies=currencies,
        importers=importers
    )
