from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import pandas as pd
from data_sources import DataConnector

# Load environment variables
load_dotenv()

# Create necessary directories before setting up logging
os.makedirs('logs', exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/audit_log.txt', mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize DataConnector
connector = DataConnector({})

# Google Sheets URLs from environment
INVENTORY_SHEET_URL = os.getenv('INVENTORY_SHEET_URL')
SOLD_ITEMS_SHEET_URL = os.getenv('SOLD_ITEMS_SHEET_URL')
INVOICES_SHEET_URL = os.getenv('INVOICES_SHEET_URL')
CUSTOMERS_SHEET_URL = os.getenv('CUSTOMERS_SHEET_URL')
USED_FREEBIE_SHEET_URL = os.getenv('USED_FREEBIE_SHEET_URL')  # Used/Freebie items
INDEX_SHEET_URL = os.getenv('INDEX_SHEET_URL')  # Product names index

@app.route('/')
def index():
    return redirect(url_for('inventory'))

@app.route('/inventory')
def inventory():
    """Main inventory management page"""
    try:
        if INVENTORY_SHEET_URL:
            df = connector.read_from_sheets(INVENTORY_SHEET_URL)
            # Calculate remaining_qty if missing
            if 'remaining_qty' not in df.columns:
                if 'total_bought_quantity' in df.columns:
                    df['remaining_qty'] = df['total_bought_quantity']
                else:
                    df['remaining_qty'] = df['quantity']
            # Ensure total_bought_quantity exists
            if 'total_bought_quantity' not in df.columns:
                df['total_bought_quantity'] = df['quantity']
            inventory_items = df.to_dict('records')
        else:
            inventory_items = []
    except Exception as e:
        logger.error(f"Error loading inventory: {str(e)}")
        inventory_items = []
        flash(f"Error loading inventory: {str(e)}", "error")
    
    # Load product names from INDEX sheet column A for dropdown
    product_names = []
    try:
        if INDEX_SHEET_URL:
            index_df = connector.read_from_sheets(INDEX_SHEET_URL)
            # Get product names from column A (first column)
            if not index_df.empty:
                # Use first column (column A)
                product_names = index_df.iloc[:, 0].dropna().unique().tolist()
                # Filter out empty strings
                product_names = [p for p in product_names if str(p).strip()]
    except Exception as e:
        logger.warning(f"Could not load INDEX sheet: {str(e)}")
        product_names = []
    
    return render_template('inventory.html', items=inventory_items, product_names=product_names)

@app.route('/api/add_product', methods=['POST'])
def add_product():
    """Add a new product to inventory"""
    try:
        data = request.json
        product_name = data.get('product_name')
        total_price = float(data.get('total_price', 0))
        shipping_admin_fee = float(data.get('shipping_admin_fee', 0))
        quantity = int(data.get('quantity', 1))
        remarks = data.get('remarks', '')
        status = data.get('status', 'in_stock')
        
        # Calculate total cost per unit: (total_price + shipping_admin_fee) / quantity
        total_cost_per_unit = (total_price + shipping_admin_fee) / quantity if quantity > 0 else 0
        total_bought_quantity = quantity
        remaining_qty = quantity  # Initially, remaining equals total bought
        
        new_product = {
            'product_name': product_name,
            'total_price': total_price,
            'shipping_admin_fee': shipping_admin_fee,
            'total_cost_per_unit': total_cost_per_unit,
            'quantity': quantity,
            'total_bought_quantity': total_bought_quantity,
            'remaining_qty': remaining_qty,
            'status': status,
            'remarks': remarks,
            'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        if INVENTORY_SHEET_URL:
            # Read existing data
            df = connector.read_from_sheets(INVENTORY_SHEET_URL)
            # Handle empty DataFrame - ensure all columns exist
            if df.empty:
                df = pd.DataFrame(columns=['product_name', 'total_price', 'shipping_admin_fee', 'total_cost_per_unit', 'quantity', 'total_bought_quantity', 'remaining_qty', 'status', 'remarks', 'date_added'])
            else:
                # Ensure new columns exist in existing DataFrame
                if 'total_bought_quantity' not in df.columns:
                    df['total_bought_quantity'] = df['quantity'] if 'quantity' in df.columns else 0
                if 'remaining_qty' not in df.columns:
                    df['remaining_qty'] = df['total_bought_quantity'] if 'total_bought_quantity' in df.columns else df['quantity']
            # Add new row using pd.concat (append is deprecated)
            new_df = pd.DataFrame([new_product])
            df = pd.concat([df, new_df], ignore_index=True)
            # Write back
            connector.write_to_sheets(df, INVENTORY_SHEET_URL)
            logger.info(f"Added product: {product_name}")
        
        return jsonify({'success': True, 'message': 'Product added successfully'})
    except Exception as e:
        logger.error(f"Error adding product: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/update_status', methods=['POST'])
def update_status():
    """Update product status (used, freebie, raffled, sold)"""
    try:
        data = request.json
        product_id = data.get('product_id')
        new_status = data.get('status')
        selling_price = data.get('selling_price')
        quantity_used = int(data.get('quantity_used', 1))  # How many items were sold/used/given
        remarks = data.get('remarks', '')
        
        if INVENTORY_SHEET_URL:
            df = connector.read_from_sheets(INVENTORY_SHEET_URL)
            
            # Update status
            if product_id < len(df):
                # Get current remaining quantity
                current_remaining = int(df.at[product_id, 'remaining_qty']) if 'remaining_qty' in df.columns and pd.notna(df.at[product_id, 'remaining_qty']) else int(df.at[product_id, 'quantity'])
                
                # Decrement remaining_qty if status is sold, used, or freebie
                if new_status in ['sold', 'used', 'freebie']:
                    new_remaining = max(0, current_remaining - quantity_used)
                    df.at[product_id, 'remaining_qty'] = new_remaining
                    # Update quantity to reflect remaining
                    df.at[product_id, 'quantity'] = new_remaining
                
                df.at[product_id, 'status'] = new_status
                df.at[product_id, 'remarks'] = remarks
                
                if new_status == 'sold' and selling_price:
                    selling_price = float(selling_price)
                    # Get total cost per unit and quantity used
                    total_cost_per_unit = float(df.at[product_id, 'total_cost_per_unit'])
                    # Total cost = total_cost_per_unit * quantity_used (not remaining quantity)
                    total_cost = total_cost_per_unit * quantity_used
                    profit = selling_price - total_cost
                    tithe = profit * 0.10  # 10% tithe
                    profit_after_tithe = profit - tithe
                    
                    df.at[product_id, 'selling_price'] = selling_price
                    df.at[product_id, 'profit'] = profit
                    df.at[product_id, 'tithe'] = tithe
                    df.at[product_id, 'profit_after_tithe'] = profit_after_tithe
                    df.at[product_id, 'date_sold'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Also add to sold items sheet
                    if SOLD_ITEMS_SHEET_URL:
                        sold_df = connector.read_from_sheets(SOLD_ITEMS_SHEET_URL)
                        # Handle empty DataFrame - match your spreadsheet structure
                        if sold_df.empty:
                            sold_df = pd.DataFrame(columns=['product_name', 'quantity', 'total_cost_per_unit', 'selling_price', 'total_cost', 'profit', 'tithe', 'profit_after_tithe', 'tithe_kept', 'remarks', 'date_sold'])
                        sold_item = {
                            'product_name': df.at[product_id, 'product_name'],
                            'quantity': quantity_used,
                            'total_cost_per_unit': total_cost_per_unit,
                            'selling_price': selling_price,
                            'total_cost': total_cost,
                            'profit': profit,
                            'tithe': tithe,
                            'profit_after_tithe': profit_after_tithe,
                            'tithe_kept': False,  # Default to not kept
                            'remarks': remarks,
                            'date_sold': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        new_sold_df = pd.DataFrame([sold_item])
                        sold_df = pd.concat([sold_df, new_sold_df], ignore_index=True)
                        connector.write_to_sheets(sold_df, SOLD_ITEMS_SHEET_URL)
                
                # Track used/freebie items
                if new_status in ['used', 'freebie']:
                    if USED_FREEBIE_SHEET_URL:
                        used_df = connector.read_from_sheets(USED_FREEBIE_SHEET_URL)
                        if used_df.empty:
                            used_df = pd.DataFrame(columns=['product_name', 'quantity', 'total_cost_per_unit', 'status', 'remarks', 'date_used'])
                        used_item = {
                            'product_name': df.at[product_id, 'product_name'],
                            'quantity': quantity_used,
                            'total_cost_per_unit': float(df.at[product_id, 'total_cost_per_unit']),
                            'status': new_status,
                            'remarks': remarks,
                            'date_used': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        new_used_df = pd.DataFrame([used_item])
                        used_df = pd.concat([used_df, new_used_df], ignore_index=True)
                        connector.write_to_sheets(used_df, USED_FREEBIE_SHEET_URL)
                
                connector.write_to_sheets(df, INVENTORY_SHEET_URL)
                logger.info(f"Updated product {product_id} status to {new_status}, remaining_qty: {df.at[product_id, 'remaining_qty']}")
            
        return jsonify({'success': True, 'message': 'Status updated successfully'})
    except Exception as e:
        logger.error(f"Error updating status: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/sold')
def sold():
    """Sold items page with tithe tracking"""
    try:
        if SOLD_ITEMS_SHEET_URL:
            df = connector.read_from_sheets(SOLD_ITEMS_SHEET_URL)
            sold_items = df.to_dict('records')
        else:
            sold_items = []
    except Exception as e:
        logger.error(f"Error loading sold items: {str(e)}")
        sold_items = []
        flash(f"Error loading sold items: {str(e)}", "error")
    
    # Calculate totals
    total_profit = sum(float(item.get('profit', 0) or 0) for item in sold_items)
    total_tithe = sum(float(item.get('tithe', 0) or 0) for item in sold_items)
    total_profit_after_tithe = sum(float(item.get('profit_after_tithe', 0) or 0) for item in sold_items)
    # Handle tithe_kept as boolean or string from Google Sheets
    tithe_kept_total = sum(
        float(item.get('tithe', 0) or 0) 
        for item in sold_items 
        if item.get('tithe_kept') == True or str(item.get('tithe_kept', '')).lower() == 'true'
    )
    
    return render_template('sold.html', 
                         items=sold_items,
                         total_profit=total_profit,
                         total_tithe=total_tithe,
                         total_profit_after_tithe=total_profit_after_tithe,
                         tithe_kept_total=tithe_kept_total)

@app.route('/api/update_tithe_status', methods=['POST'])
def update_tithe_status():
    """Update whether tithe has been kept"""
    try:
        data = request.json
        item_id = data.get('item_id')
        tithe_kept = data.get('tithe_kept', False)
        
        if SOLD_ITEMS_SHEET_URL:
            df = connector.read_from_sheets(SOLD_ITEMS_SHEET_URL)
            if item_id < len(df):
                df.at[item_id, 'tithe_kept'] = tithe_kept
                connector.write_to_sheets(df, SOLD_ITEMS_SHEET_URL)
                logger.info(f"Updated tithe status for item {item_id}")
        
        return jsonify({'success': True, 'message': 'Tithe status updated'})
    except Exception as e:
        logger.error(f"Error updating tithe status: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/used_freebie')
def used_freebie():
    """Used and Freebie items page"""
    try:
        if USED_FREEBIE_SHEET_URL:
            df = connector.read_from_sheets(USED_FREEBIE_SHEET_URL)
            used_items = df.to_dict('records') if not df.empty else []
        else:
            used_items = []
    except Exception as e:
        logger.error(f"Error loading used/freebie items: {str(e)}", exc_info=True)
        used_items = []
        flash(f"Error loading used/freebie items: {str(e)}", "error")
    
    # Separate used and freebie
    try:
        used = [item for item in used_items if item.get('status', '').lower() == 'used']
        freebie = [item for item in used_items if item.get('status', '').lower() == 'freebie']
    except Exception as e:
        logger.error(f"Error processing used/freebie items: {str(e)}", exc_info=True)
        used = []
        freebie = []
    
    return render_template('used_freebie.html', used_items=used, freebie_items=freebie)

@app.route('/invoices')
def invoices():
    """Invoice creation page"""
    import json
    try:
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            invoices = df.to_dict('records')
            # Parse items JSON for each invoice
            for invoice in invoices:
                items_str = invoice.get('items', '[]')
                try:
                    invoice['items_parsed'] = json.loads(items_str) if isinstance(items_str, str) else items_str
                except:
                    invoice['items_parsed'] = []
        else:
            invoices = []
        
        if CUSTOMERS_SHEET_URL:
            customers_df = connector.read_from_sheets(CUSTOMERS_SHEET_URL)
            customers = customers_df.to_dict('records')
            # Parse products_purchased JSON for each customer
            for customer in customers:
                products_str = customer.get('products_purchased', '{}')
                try:
                    customer['products_parsed'] = json.loads(products_str) if isinstance(products_str, str) else products_str
                except:
                    customer['products_parsed'] = {}
        else:
            customers = []
        
        # Load product names from INDEX sheet for dropdown
        product_names = []
        try:
            if INDEX_SHEET_URL:
                index_df = connector.read_from_sheets(INDEX_SHEET_URL)
                if not index_df.empty:
                    product_names = index_df.iloc[:, 0].dropna().unique().tolist()
                    product_names = [p for p in product_names if str(p).strip()]
        except Exception as e:
            logger.warning(f"Could not load INDEX sheet: {str(e)}")
            product_names = []
    except Exception as e:
        logger.error(f"Error loading invoices: {str(e)}")
        invoices = []
        customers = []
        product_names = []
        flash(f"Error loading invoices: {str(e)}", "error")
    
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('invoices.html', invoices=invoices, customers=customers, product_names=product_names, today=today)

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    logger.error(f"Internal Server Error: {str(error)}", exc_info=True)
    error_msg = "An internal error occurred. Please check Railway logs for details."
    try:
        return render_template('error.html', error_message=error_msg), 500
    except:
        # Fallback if error template doesn't exist
        return f"<h1>Internal Server Error</h1><p>{error_msg}</p>", 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    logger.warning(f"404 Error: {str(error)}")
    try:
        return render_template('error.html', error_message="Page not found."), 404
    except:
        return "<h1>404 - Page Not Found</h1>", 404

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    logger.error(f"Internal Server Error: {str(error)}", exc_info=True)
    return render_template('error.html', error_message="An internal error occurred. Please check the logs."), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    logger.warning(f"404 Error: {str(error)}")
    return render_template('error.html', error_message="Page not found."), 404

@app.route('/api/create_invoice', methods=['POST'])
def create_invoice():
    """Create a new invoice"""
    try:
        data = request.json
        customer_name = data.get('customer_name')
        items = data.get('items', [])
        total_amount = float(data.get('total_amount', 0))
        invoice_date = data.get('invoice_date', datetime.now().strftime('%Y-%m-%d'))
        
        invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{len(items)}"
        
        new_invoice = {
            'invoice_number': invoice_number,
            'customer_name': customer_name,
            'items': str(items),  # Store as string representation
            'total_amount': total_amount,
            'invoice_date': invoice_date,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            # Handle empty DataFrame
            if df.empty:
                df = pd.DataFrame(columns=['invoice_number', 'customer_name', 'items', 'total_amount', 'invoice_date', 'created_at'])
            new_invoice_df = pd.DataFrame([new_invoice])
            df = pd.concat([df, new_invoice_df], ignore_index=True)
            connector.write_to_sheets(df, INVOICES_SHEET_URL)
        
        # Update customer records with product-level details
        if CUSTOMERS_SHEET_URL:
            import json
            customers_df = connector.read_from_sheets(CUSTOMERS_SHEET_URL)
            # Handle empty DataFrame - include product details columns
            if customers_df.empty:
                customers_df = pd.DataFrame(columns=['customer_name', 'total_orders', 'total_spent', 'first_order_date', 'last_order_date', 'products_purchased'])
            
            # Parse items to get product details
            products_summary = {}
            for item in items:
                product_name = item.get('name', '')
                qty = item.get('quantity', 0)
                price = item.get('price', 0)
                if product_name:
                    if product_name not in products_summary:
                        products_summary[product_name] = {'qty': 0, 'total_amount': 0}
                    products_summary[product_name]['qty'] += qty
                    products_summary[product_name]['total_amount'] += price * qty
            
            if customer_name not in customers_df['customer_name'].values:
                new_customer = {
                    'customer_name': customer_name,
                    'total_orders': 1,
                    'total_spent': total_amount,
                    'first_order_date': invoice_date,
                    'last_order_date': invoice_date,
                    'products_purchased': json.dumps(products_summary)
                }
                new_customer_df = pd.DataFrame([new_customer])
                customers_df = pd.concat([customers_df, new_customer_df], ignore_index=True)
            else:
                # Update existing customer
                idx = customers_df[customers_df['customer_name'] == customer_name].index[0]
                customers_df.at[idx, 'total_orders'] = int(customers_df.at[idx, 'total_orders']) + 1
                customers_df.at[idx, 'total_spent'] = float(customers_df.at[idx, 'total_spent']) + total_amount
                customers_df.at[idx, 'last_order_date'] = invoice_date
                
                # Merge product purchases
                existing_products = {}
                if 'products_purchased' in customers_df.columns and pd.notna(customers_df.at[idx, 'products_purchased']):
                    try:
                        existing_products = json.loads(str(customers_df.at[idx, 'products_purchased']))
                    except:
                        existing_products = {}
                
                # Merge new products with existing
                for product_name, details in products_summary.items():
                    if product_name in existing_products:
                        existing_products[product_name]['qty'] += details['qty']
                        existing_products[product_name]['total_amount'] += details['total_amount']
                    else:
                        existing_products[product_name] = details
                
                customers_df.at[idx, 'products_purchased'] = json.dumps(existing_products)
            connector.write_to_sheets(customers_df, CUSTOMERS_SHEET_URL)
        
        logger.info(f"Created invoice {invoice_number} for {customer_name}")
        return jsonify({'success': True, 'message': 'Invoice created successfully', 'invoice_number': invoice_number})
    except Exception as e:
        logger.error(f"Error creating invoice: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 400

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    
    # Get port from environment (Railway sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    # Debug mode only in development (not production)
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

