import os
import requests
from datetime import datetime
from decimal import Decimal
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from sqlalchemy import cast, String

from ..models import db, Order, ExpenseInvoice, ExpenseItem, Provider, Account
from ..utils.currency import usd_to_cad

bp = Blueprint('utilities', __name__, template_folder='templates/utilities')


@bp.route('/')
def index():
    """Utilities dashboard with various utility options"""
    return render_template('utilities/index.html')


@bp.route('/printify-import', methods=['GET', 'POST'])
def printify_import():
    """Import COGS data from Printify API for orders missing cost data"""
    
    if request.method == 'GET':
        # Pre-fill from config if available
        api_token = current_app.config.get('PRINTIFY_API_TOKEN', '')
        shop_id = current_app.config.get('PRINTIFY_SHOP_ID', '')
        return render_template('utilities/printify_import.html', 
                             api_token=api_token, 
                             shop_id=shop_id)
    
    # POST: Execute the import
    api_token = request.form.get('api_token', '').strip()
    shop_id = request.form.get('shop_id', '').strip()
    
    if not api_token or not shop_id:
        flash('API Token and Shop ID are required', 'warning')
        return redirect(url_for('utilities.printify_import'))
    
    try:
        # Find orders without COGS data
        orders_without_cogs = find_orders_without_cogs()
        
        if not orders_without_cogs:
            flash('All orders already have COGS data!', 'info')
            return redirect(url_for('utilities.index'))
        
        current_app.logger.info(f"Found {len(orders_without_cogs)} orders without COGS")
        
        # Import from Printify API
        results = import_from_printify_api(api_token, shop_id, orders_without_cogs)
        
        flash(f"Successfully imported COGS for {results['success']} orders. "
              f"Skipped {results['skipped']} orders. "
              f"Failed {results['failed']} orders.", 
              'success' if results['failed'] == 0 else 'warning')
        
    except Exception as e:
        current_app.logger.error(f"Printify import error: {e}")
        flash(f'Error during import: {str(e)}', 'danger')
    
    return redirect(url_for('utilities.index'))


def find_orders_without_cogs():
    """Find orders that don't have complete COGS expense items (production cost or tax)"""
    # Check for orders that have BOTH production COGS AND tax
    # We want to re-import orders missing either one
    
    # Get all order numbers that have COGS production cost
    orders_with_prod_cogs = (
        db.session.query(cast(ExpenseItem.order_id, String))
        .join(Account, ExpenseItem.account_id == Account.id)
        .filter(Account.name == 'COGS')
        .distinct()
        .all()
    )
    orders_with_prod_cogs_set = {row[0] for row in orders_with_prod_cogs}
    
    # Get all order numbers that have COGS tax
    orders_with_tax = (
        db.session.query(cast(ExpenseItem.order_id, String))
        .join(Account, ExpenseItem.account_id == Account.id)
        .filter(Account.name == 'COGS Tax')
        .distinct()
        .all()
    )
    orders_with_tax_set = {row[0] for row in orders_with_tax}
    
    # Get all orders
    all_orders = Order.query.all()
    
    # Filter to those without BOTH production cost AND tax
    orders_without_complete_cogs = [
        order for order in all_orders 
        if order.order_number not in orders_with_prod_cogs_set 
        or order.order_number not in orders_with_tax_set
    ]
    
    return orders_without_complete_cogs


def import_from_printify_api(api_token, shop_id, orders):
    """
    Import COGS data from Printify API for the given orders.
    Uses Shopify order number to match Printify orders.
    """
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }
    
    # Get account IDs
    product_sale_acc = Account.query.filter_by(name='COGS').first()
    cust_shipping_acc = Account.query.filter_by(name='COGS Shipping').first()
    sales_tax_acc = Account.query.filter_by(name='COGS Tax').first()
    
    if not all([product_sale_acc, cust_shipping_acc, sales_tax_acc]):
        raise Exception("Required COGS accounts not found. Please ensure 'COGS', 'COGS Shipping', and 'COGS Tax' accounts exist.")
    
    # Get Printify provider
    printify_provider = Provider.query.filter_by(name='Printify').first()
    if not printify_provider:
        raise Exception("Printify provider not found. Please create a provider named 'Printify'.")
    
    results = {'success': 0, 'skipped': 0, 'failed': 0}
    
    # Fetch all Printify orders first (with pagination)
    printify_orders_map = {}
    page = 1
    has_more = True
    
    current_app.logger.info(f"Fetching orders from Printify API for shop {shop_id}")
    
    while has_more:
        try:
            # Printify API endpoint needs .json extension
            url = f'https://api.printify.com/v1/shops/{shop_id}/orders.json'
            params = {'page': page, 'limit': 50}  # Max 100 per page
            
            current_app.logger.info(f"Requesting: {url} with params: {params}")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            # Log response for debugging
            current_app.logger.info(f"Response status: {response.status_code}")
            if response.status_code != 200:
                current_app.logger.error(f"Response body: {response.text}")
            
            response.raise_for_status()
            
            data = response.json()
            orders_data = data.get('data', [])
            
            current_app.logger.info(f"Page {page}: Found {len(orders_data)} orders")
            
            if not orders_data:
                has_more = False
            else:
                # Build a map of shopify order number -> printify order
                for p_order in orders_data:
                    metadata = p_order.get('metadata', {})
                    # Try various fields where Shopify order number might be stored
                    shopify_num = (metadata.get('shop_order_label') or 
                                  metadata.get('shopify_order_number') or 
                                  p_order.get('label', ''))
                    
                    # Strip the # if present
                    shopify_num = shopify_num.lstrip('#')
                    
                    if shopify_num:
                        printify_orders_map[shopify_num] = p_order
                        current_app.logger.debug(f"Mapped Shopify order {shopify_num} to Printify order {p_order.get('id')}")
                
                # Check if there are more pages
                current_page = data.get('current_page', page)
                last_page = data.get('last_page', page)
                has_more = current_page < last_page
                
                if has_more:
                    page += 1
                
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Error fetching Printify orders page {page}: {e}")
            has_more = False
    
    current_app.logger.info(f"Found {len(printify_orders_map)} Printify orders with Shopify order numbers")
    
    # Now process each order that needs COGS
    for order in orders:
        try:
            matching_order = printify_orders_map.get(order.order_number)
            
            if not matching_order:
                current_app.logger.warning(f"No Printify order found for {order.order_number}")
                results['skipped'] += 1
                continue
            
            # Extract cost data from line items
            product_cost = Decimal('0')
            shipping_cost = Decimal('0')
            
            line_items = matching_order.get('line_items', [])
            for item in line_items:
                # Printify costs are in cents
                item_product_cost = Decimal(str(item.get('cost', 0))) / 100
                item_shipping_cost = Decimal(str(item.get('shipping_cost', 0))) / 100
                
                product_cost += item_product_cost
                shipping_cost += item_shipping_cost
            
            # Get sales tax from order level (in cents)
            tax_cost = Decimal(str(matching_order.get('total_tax', 0))) / 100
            
            total_cost = product_cost + shipping_cost + tax_cost
            
            if total_cost == 0:
                current_app.logger.warning(f"Zero cost for order {order.order_number}")
                results['skipped'] += 1
                continue
            
            # Check if invoice already exists for this order
            existing_inv = ExpenseInvoice.query.filter_by(
                provider_id=printify_provider.id,
                invoice_number=order.order_number
            ).first()
            
            if existing_inv:
                # Update existing invoice
                exp_inv = existing_inv
                exp_inv.total_amount = total_cost
                exp_inv.supplier_invoice = matching_order.get('id')
                current_app.logger.info(f"Updating existing invoice for order {order.order_number}")
            else:
                # Create new expense invoice
                exp_inv = ExpenseInvoice(
                    provider_id=printify_provider.id,
                    invoice_date=order.order_date,
                    invoice_number=order.order_number,
                    supplier_invoice=matching_order.get('id'),
                    total_amount=total_cost
                )
                db.session.add(exp_inv)
                db.session.flush()
            
            # Add expense items (linking to order by order_number as string)
            # Only add production cost if it doesn't already exist
            if product_cost > 0:
                existing_prod_item = ExpenseItem.query.filter_by(
                    expense_invoice_id=exp_inv.id,
                    account_id=product_sale_acc.id
                ).first()
                
                if not existing_prod_item:
                    db.session.add(ExpenseItem(
                        expense_invoice_id=exp_inv.id,
                        account_id=product_sale_acc.id,
                        description='Production Cost (Printify API)',
                        amount=product_cost,
                        currency_code='USD',
                        order_id=order.order_number
                    ))
                    current_app.logger.info(f"Added production cost ${product_cost} for order {order.order_number}")
            
            # Only add shipping cost if it doesn't already exist
            if shipping_cost > 0:
                existing_ship_item = ExpenseItem.query.filter_by(
                    expense_invoice_id=exp_inv.id,
                    account_id=cust_shipping_acc.id
                ).first()
                
                if not existing_ship_item:
                    db.session.add(ExpenseItem(
                        expense_invoice_id=exp_inv.id,
                        account_id=cust_shipping_acc.id,
                        description='Shipping Cost (Printify API)',
                        amount=shipping_cost,
                        currency_code='USD',
                        order_id=order.order_number
                    ))
            
            # Only add sales tax if it doesn't already exist (one per order)
            if tax_cost > 0:
                existing_tax_item = ExpenseItem.query.filter_by(
                    expense_invoice_id=exp_inv.id,
                    account_id=sales_tax_acc.id
                ).first()
                
                if not existing_tax_item:
                    db.session.add(ExpenseItem(
                        expense_invoice_id=exp_inv.id,
                        account_id=sales_tax_acc.id,
                        description='Sales Tax Charged (Printify API)',
                        amount=tax_cost,
                        currency_code='USD',
                        order_id=order.order_number
                    ))
            
            current_app.logger.info(f"Imported COGS for order {order.order_number}: Product ${product_cost}, Shipping ${shipping_cost}, Tax ${tax_cost}")
            results['success'] += 1
            
        except Exception as e:
            current_app.logger.error(f"Error processing order {order.order_number}: {e}")
            results['failed'] += 1
            continue
    
    # Commit all changes
    db.session.commit()
    
    return results
