import os
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, current_app
)
from app.models import Provider, Currency, Account, db

bp = Blueprint('providers', __name__, template_folder='templates/providers')


def _form_context(provider=None, form_data=None):
    """Build common context for both create & edit."""
    # load lookups
    currencies = Currency.query.order_by(Currency.code).all()
    accounts = Account.query.order_by(Account.name).all()
    # scan importers folder
    imp_dir = os.path.join(current_app.root_path, 'importers')
    files = os.listdir(imp_dir) if os.path.isdir(imp_dir) else []
    importers = sorted(f[:-3] for f in files if f.endswith('.py') and f != '__init__.py')

    # base form values = either provider's or empty
    base = {
        'name': provider.name if provider else '',
        'type': provider.type if provider else None,
        'currency_code': provider.currency_code if provider else None,
        'importer': provider.importer if provider else None,
        'default_account_id': provider.default_account_id if provider else None,
        'contact_info': provider.contact_info if provider else '',
        'notes': provider.notes if provider else '',
    }
    # override from explicit form_data if present
    if form_data:
        base.update({k: form_data.get(k) for k in base.keys()})
    return {
        'provider': provider,
        'currencies': currencies,
        'accounts': accounts,
        'importers': importers,
        'form': base
    }


@bp.route('/')
def list_providers():
    providers = Provider.query.order_by(Provider.id).all()
    return render_template('providers/list.html', providers=providers)


@bp.route('/new', methods=['GET', 'POST'])
def create_provider():
    if request.method == 'POST':
        form = request.form
        name = form.get('name', '').strip()
        if not name or not form.get('type') or not form.get('currency_code'):
            flash('Name, Type, and Currency are required.', 'warning')
            return render_template('providers/form.html', **_form_context(None, form))

        if Provider.query.filter_by(name=name).first():
            flash(f'Provider "{name}" already exists.', 'warning')
            return redirect(url_for('providers.list_providers'))

        p = Provider(
            name=name,
            type=form.get('type'),
            currency_code=form.get('currency_code'),
            importer=form.get('importer') or None,
            default_account_id=form.get('default_account_id', type=int),
            contact_info=form.get('contact_info', '').strip(),
            notes=form.get('notes', '').strip()
        )
        db.session.add(p)
        db.session.commit()
        flash(f'Provider "{name}" created.', 'success')
        return redirect(url_for('providers.list_providers'))

    return render_template('providers/form.html', **_form_context())


@bp.route('/<int:provider_id>', methods=['GET', 'POST'])
def edit_provider(provider_id):
    provider = Provider.query.get_or_404(provider_id)

    if request.method == 'POST':
        form = request.form
        name = form.get('name', '').strip()
        if not name or not form.get('type') or not form.get('currency_code'):
            flash('Name, Type, and Currency are required.', 'warning')
            return render_template('providers/form.html', **_form_context(provider, form))

        exists = Provider.query.filter(
            Provider.name == name, Provider.id != provider_id
        ).first()
        if exists:
            flash(f'Provider "{name}" already exists.', 'warning')
            return redirect(url_for('providers.list_providers'))

        # apply updates
        provider.name = name
        provider.type = form.get('type')
        provider.currency_code = form.get('currency_code')
        provider.importer = form.get('importer') or None
        provider.default_account_id = form.get('default_account_id', type=int)
        provider.contact_info = form.get('contact_info', '').strip()
        provider.notes = form.get('notes', '').strip()
        db.session.commit()

        flash(f'Provider "{name}" updated.', 'success')
        return redirect(url_for('providers.list_providers'))

    return render_template('providers/form.html', **_form_context(provider))
