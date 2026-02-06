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

def format_date_custom(date_str):
    """Format date string to 'Jan162026 9:30PM' format"""
    if not date_str or pd.isna(date_str):
        return '-'
    try:
        # Try parsing different date formats
        if isinstance(date_str, str):
            # Try common formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                # Try pandas parsing
                dt = pd.to_datetime(date_str, errors='coerce')
                if pd.isna(dt):
                    return date_str
        else:
            dt = pd.to_datetime(date_str, errors='coerce')
            if pd.isna(dt):
                return str(date_str)
        
        # Format: Jan162026 9:30PM
        month_abbr = dt.strftime('%b')  # Jan, Feb, etc.
        day = dt.strftime('%d').lstrip('0') or '0'  # Remove leading zero
        year = dt.strftime('%Y')
        hour = int(dt.strftime('%I').lstrip('0') or '12')  # 12-hour format, remove leading zero
        minute = dt.strftime('%M')
        am_pm = dt.strftime('%p')  # AM/PM
        
        return f"{month_abbr}{day}{year} {hour}:{minute}{am_pm}"
    except Exception as e:
        logger.warning(f"Error formatting date '{date_str}': {str(e)}")
        return str(date_str)

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
            
            # Handle empty DataFrame
            if df.empty:
                logger.info("Inventory sheet is empty")
                inventory_items = []
                product_summary_list = []
            else:
                # Calculate remaining_qty if missing
                if 'remaining_qty' not in df.columns:
                    if 'total_bought_quantity' in df.columns:
                        df['remaining_qty'] = df['total_bought_quantity']
                    elif 'quantity' in df.columns:
                        df['remaining_qty'] = df['quantity']
                    else:
                        df['remaining_qty'] = 0
                
                # Ensure total_bought_quantity exists
                if 'total_bought_quantity' not in df.columns:
                    if 'quantity' in df.columns:
                        df['total_bought_quantity'] = df['quantity']
                    else:
                        df['total_bought_quantity'] = 0
                
                # Sort by product_name alphabetically, then by date_added (newest first for same product)
                if 'product_name' in df.columns:
                    # Convert date_added to datetime for proper sorting
                    if 'date_added' in df.columns:
                        df['date_added_parsed'] = pd.to_datetime(df['date_added'], errors='coerce')
                        df = df.sort_values(['product_name', 'date_added_parsed'], ascending=[True, False], na_position='last')
                        df = df.drop('date_added_parsed', axis=1)
                    else:
                        df = df.sort_values('product_name', ascending=True)
                
                # Format dates before converting to dict
                if 'date_added' in df.columns:
                    df['date_added'] = df['date_added'].apply(format_date_custom)
                if 'date_sold' in df.columns:
                    df['date_sold'] = df['date_sold'].apply(format_date_custom)
                
                # Ensure all columns are present with defaults
                required_cols = ['product_name', 'total_price', 'shipping_admin_fee', 'total_cost_per_unit', 
                                'quantity', 'total_bought_quantity', 'remaining_qty', 'supplier', 
                                'date_added', 'remarks', 'status', 'selling_price', 'profit', 
                                'tithe', 'profit_after_tithe', 'date_sold']
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = None if col in ['remarks', 'status', 'supplier', 'date_sold'] else 0
                
                inventory_items = df.to_dict('records')
                
                # Calculate product summary (grouped by product_name) - optimized
                product_summary = {}
                for item in inventory_items:
                    product_name = str(item.get('product_name', 'Unknown')).strip()
                    if not product_name or product_name == 'Unknown':
                        continue
                    
                    if product_name not in product_summary:
                        product_summary[product_name] = {
                            'product_name': product_name,
                            'total_quantity': 0,
                            'total_remaining': 0,
                            'entry_count': 0
                        }
                    # Safely convert quantities - use vectorized operations where possible
                    try:
                        qty_val = item.get('quantity', 0)
                        remaining_val = item.get('remaining_qty', qty_val)
                        qty = int(float(str(qty_val))) if qty_val else 0
                        remaining = int(float(str(remaining_val))) if remaining_val else 0
                    except (ValueError, TypeError):
                        qty = 0
                        remaining = 0
                    product_summary[product_name]['total_quantity'] += qty
                    product_summary[product_name]['total_remaining'] += remaining
                    product_summary[product_name]['entry_count'] += 1
                
                # Convert summary dict to list sorted by product name
                product_summary_list = sorted(product_summary.values(), key=lambda x: x['product_name'].lower())
        else:
            inventory_items = []
            product_summary_list = []
    except KeyError as e:
        # Handle missing column errors with user-friendly message
        missing_column = str(e).strip("'\"")
        logger.error(f"Error loading inventory: Missing column '{missing_column}' in spreadsheet", exc_info=True)
        inventory_items = []
        product_summary_list = []
        flash(f"Your inventory spreadsheet is missing the '{missing_column}' column. Please add this column to your Google Sheet.", "error")
    except Exception as e:
        error_msg = str(e)
        # Convert technical errors to user-friendly messages
        if "Google Sheets client not initialized" in error_msg:
            user_msg = "Unable to connect to Google Sheets. Please check that your credentials are set up correctly in the environment variables."
        elif "quantity" in error_msg.lower() or "column" in error_msg.lower():
            user_msg = "Your inventory spreadsheet structure doesn't match what the app expects. Please check that all required columns are present in your Google Sheet."
        else:
            user_msg = f"Unable to load inventory. Please check your Google Sheet connection and try again. ({error_msg[:100]})"
        
        logger.error(f"Error loading inventory: {error_msg}", exc_info=True)
        inventory_items = []
        product_summary_list = []
        flash(user_msg, "error")
    
    # Load product names from INDEX sheet product_name column for dropdown (cached per request)
    product_names = []
    try:
        if INDEX_SHEET_URL:
            index_df = connector.read_from_sheets(INDEX_SHEET_URL)
            # Get product names from product_name column (or first column if column doesn't exist)
            if not index_df.empty and len(index_df.columns) > 0:
                if 'product_name' in index_df.columns:
                    product_names = index_df['product_name'].dropna().unique().tolist()
                else:
                    # Fallback to first column if product_name column doesn't exist
                    product_names = index_df.iloc[:, 0].dropna().unique().tolist()
                # Filter out empty strings
                product_names = [p for p in product_names if str(p).strip()]
                logger.info(f"Loaded {len(product_names)} product names from INDEX sheet")
            else:
                logger.warning("INDEX sheet is empty or has no columns")
    except Exception as e:
        logger.warning(f"Could not load INDEX sheet: {str(e)}", exc_info=True)
        product_names = []
    
    # Ensure product_summary_list is always defined (in case of errors above)
    if 'product_summary_list' not in locals():
        # Calculate product summary (grouped by product_name) if not already calculated
        product_summary = {}
        for item in inventory_items:
            product_name = str(item.get('product_name', 'Unknown')).strip()
            if not product_name or product_name == 'Unknown':
                continue
                
            if product_name not in product_summary:
                product_summary[product_name] = {
                    'product_name': product_name,
                    'total_quantity': 0,
                    'total_remaining': 0,
                    'entry_count': 0
                }
            # Safely convert quantities
            try:
                qty_val = item.get('quantity', 0)
                remaining_val = item.get('remaining_qty', qty_val)
                qty = int(float(str(qty_val))) if qty_val else 0
                remaining = int(float(str(remaining_val))) if remaining_val else 0
            except (ValueError, TypeError):
                qty = 0
                remaining = 0
            product_summary[product_name]['total_quantity'] += qty
            product_summary[product_name]['total_remaining'] += remaining
            product_summary[product_name]['entry_count'] += 1
        
        # Convert summary dict to list sorted by product name
        product_summary_list = sorted(product_summary.values(), key=lambda x: x['product_name'].lower())
    
    return render_template('inventory.html', items=inventory_items, product_names=product_names, product_summary=product_summary_list)

@app.route('/api/add_product', methods=['POST'])
def add_product():
    """Add a new product to inventory"""
    try:
        data = request.json
        product_name = data.get('product_name')
        total_price = float(data.get('total_price', 0))
        shipping_admin_fee = float(data.get('shipping_admin_fee', 0))
        quantity = int(data.get('quantity', 1))
        supplier = data.get('supplier', '')
        
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
            'supplier': supplier or '',
            'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'remarks': '',
            'status': 'in_stock',
            'selling_price': None,
            'profit': None,
            'tithe': None,
            'profit_after_tithe': None,
            'date_sold': None
        }
        
        if INVENTORY_SHEET_URL:
            # Read existing data
            df = connector.read_from_sheets(INVENTORY_SHEET_URL)
            # Handle empty DataFrame - ensure all columns exist (matching your spreadsheet structure)
            if df.empty:
                df = pd.DataFrame(columns=['product_name', 'total_price', 'shipping_admin_fee', 'total_cost_per_unit', 'quantity', 'total_bought_quantity', 'remaining_qty', 'supplier', 'date_added', 'remarks', 'status', 'selling_price', 'profit', 'tithe', 'profit_after_tithe', 'date_sold'])
            else:
                # Ensure all required columns exist in existing DataFrame
                required_columns = ['product_name', 'total_price', 'shipping_admin_fee', 'total_cost_per_unit', 'quantity', 'total_bought_quantity', 'remaining_qty', 'supplier', 'date_added', 'remarks', 'status', 'selling_price', 'profit', 'tithe', 'profit_after_tithe', 'date_sold']
                for col in required_columns:
                    if col not in df.columns:
                        df[col] = None
                
                # Ensure proper data types
                numeric_cols = ['total_price', 'shipping_admin_fee', 'total_cost_per_unit', 'quantity', 'total_bought_quantity', 'remaining_qty', 'selling_price', 'profit', 'tithe', 'profit_after_tithe']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
                # Check for duplicate entry (same product_name, total_price, shipping_admin_fee, quantity, supplier within last 2 minutes)
                # This helps prevent accidental double entries - reduced time window for faster response
                recent_time = (datetime.now() - pd.Timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
                if 'date_added' in df.columns and len(df) > 0:
                    df['date_added_parsed'] = pd.to_datetime(df['date_added'], errors='coerce')
                    recent_mask = df['date_added_parsed'] >= pd.to_datetime(recent_time)
                    recent_df = df[recent_mask]
                    
                    # Check for exact duplicates
                    if len(recent_df) > 0:
                        # Handle supplier comparison (can be None/NaN/empty string)
                        supplier_col = recent_df['supplier'].fillna('') if 'supplier' in recent_df.columns else pd.Series([''] * len(recent_df))
                        supplier_to_check = supplier if supplier else ''
                        
                        # Normalize numeric values for comparison (handle float precision issues)
                        duplicate_mask = (
                            (recent_df['product_name'].astype(str).str.strip() == str(product_name).strip()) &
                            (abs(recent_df['total_price'].astype(float) - float(total_price)) < 0.01) &
                            (abs(recent_df['shipping_admin_fee'].astype(float) - float(shipping_admin_fee)) < 0.01) &
                            (recent_df['quantity'].astype(int) == int(quantity)) &
                            (supplier_col.astype(str).str.strip() == str(supplier_to_check).strip())
                        )
                        
                        if duplicate_mask.any():
                            logger.warning(f"Potential duplicate entry detected for {product_name} (supplier: {supplier})")
                            return jsonify({'success': False, 'message': 'A similar entry was added recently (within last 2 minutes). Please check if this is a duplicate.'}), 400
                    
                    df = df.drop('date_added_parsed', axis=1)
            
            # Add new row using pd.concat (append is deprecated)
            new_df = pd.DataFrame([new_product])
            df = pd.concat([df, new_df], ignore_index=True)
            # Write back
            connector.write_to_sheets(df, INVENTORY_SHEET_URL)
            logger.info(f"Added product: {product_name} (supplier: {supplier})")
        
        return jsonify({'success': True, 'message': 'Product added successfully'})
    except KeyError as e:
        missing_column = str(e).strip("'\"")
        logger.error(f"Error adding product: Missing column '{missing_column}' in spreadsheet", exc_info=True)
        return jsonify({'success': False, 'message': f"Your spreadsheet is missing the '{missing_column}' column. Please add this column to your Google Sheet."}), 400
    except Exception as e:
        error_msg = str(e)
        if "Google Sheets client not initialized" in error_msg:
            user_msg = "Unable to connect to Google Sheets. Please check your credentials."
        elif "column" in error_msg.lower():
            user_msg = "Your spreadsheet structure doesn't match what the app expects. Please check your Google Sheet columns."
        else:
            user_msg = f"Unable to add product. Please try again. ({error_msg[:80]})"
        logger.error(f"Error adding product: {error_msg}", exc_info=True)
        return jsonify({'success': False, 'message': user_msg}), 400

@app.route('/api/update_status', methods=['POST'])
def update_status():
    """Update product status (used, freebie, raffled, sold)"""
    try:
        data = request.json
        # Convert product_id to int (might come as string from form)
        try:
            product_id = int(data.get('product_id'))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid product ID. Please refresh the page and try again.'}), 400
        
        new_status = data.get('status')
        selling_price = data.get('selling_price')
        quantity_used = int(data.get('quantity_used', 1))  # How many items were sold/used/given
        remarks = data.get('remarks', '')
        
        if INVENTORY_SHEET_URL:
            df = connector.read_from_sheets(INVENTORY_SHEET_URL)
            
            # Validate product_id is within bounds
            if df.empty or product_id < 0 or product_id >= len(df):
                return jsonify({'success': False, 'message': 'Product not found. Please refresh the page and try again.'}), 400
            
            # Helper functions to safely convert values from Google Sheets
            def safe_int(value, default=0):
                if pd.isna(value) or value is None or value == '':
                    return default
                try:
                    return int(float(str(value)))  # Convert string -> float -> int to handle "2.0" cases
                except (ValueError, TypeError):
                    return default
            
            def safe_float(value, default=0.0):
                if pd.isna(value) or value is None or value == '':
                    return default
                try:
                    return float(str(value))
                except (ValueError, TypeError):
                    return default
            
            # Get current remaining quantity
            if 'remaining_qty' in df.columns and pd.notna(df.at[product_id, 'remaining_qty']):
                current_remaining = safe_int(df.at[product_id, 'remaining_qty'], 0)
            elif 'total_bought_quantity' in df.columns and pd.notna(df.at[product_id, 'total_bought_quantity']):
                current_remaining = safe_int(df.at[product_id, 'total_bought_quantity'], 0)
            elif 'quantity' in df.columns and pd.notna(df.at[product_id, 'quantity']):
                current_remaining = safe_int(df.at[product_id, 'quantity'], 0)
            else:
                current_remaining = 0
            
            # Decrement remaining_qty if status is sold, used, or freebie
            if new_status in ['sold', 'used', 'freebie']:
                new_remaining = max(0, current_remaining - quantity_used)
                # Ensure remaining_qty column exists
                if 'remaining_qty' not in df.columns:
                    df['remaining_qty'] = current_remaining
                df.at[product_id, 'remaining_qty'] = new_remaining
                # Update quantity to reflect remaining (if column exists)
                if 'quantity' in df.columns:
                    df.at[product_id, 'quantity'] = new_remaining
            
            df.at[product_id, 'status'] = new_status
            df.at[product_id, 'remarks'] = remarks
            
            if new_status == 'sold' and selling_price:
                    
                    selling_price = safe_float(selling_price, 0.0)
                    # Get total cost per unit and quantity used
                    total_cost_per_unit = safe_float(df.at[product_id, 'total_cost_per_unit'], 0.0)
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
                            'tithe_kept': 'False',  # Default to not kept (store as string for Google Sheets)
                            'remarks': remarks,
                            'date_sold': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        new_sold_df = pd.DataFrame([sold_item])
                        # Ensure tithe_kept column is string type in existing DataFrame
                        if 'tithe_kept' in sold_df.columns:
                            sold_df['tithe_kept'] = sold_df['tithe_kept'].astype(str)
                        sold_df = pd.concat([sold_df, new_sold_df], ignore_index=True)
                        # Ensure tithe_kept column remains string type after concat
                        sold_df['tithe_kept'] = sold_df['tithe_kept'].astype(str)
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
                        'total_cost_per_unit': safe_float(df.at[product_id, 'total_cost_per_unit'], 0.0),
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
    except KeyError as e:
        missing_column = str(e).strip("'\"")
        logger.error(f"Error updating status: Missing column '{missing_column}' in spreadsheet", exc_info=True)
        return jsonify({'success': False, 'message': f"Your spreadsheet is missing the '{missing_column}' column. Please add this column to your Google Sheet."}), 400
    except Exception as e:
        error_msg = str(e)
        if "Google Sheets client not initialized" in error_msg:
            user_msg = "Unable to connect to Google Sheets. Please check your credentials."
        elif "column" in error_msg.lower() or "quantity" in error_msg.lower():
            user_msg = "Your spreadsheet structure doesn't match what the app expects. Please check your Google Sheet columns."
        else:
            user_msg = f"Unable to update status. Please try again. ({error_msg[:80]})"
        logger.error(f"Error updating status: {error_msg}", exc_info=True)
        return jsonify({'success': False, 'message': user_msg}), 400

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
    # Calculate tithe unkept (difference between total tithe and tithe kept)
    tithe_unkept_total = total_tithe - tithe_kept_total
    
    return render_template('sold.html', 
                         items=sold_items,
                         total_profit=total_profit,
                         total_tithe=total_tithe,
                         total_profit_after_tithe=total_profit_after_tithe,
                         tithe_kept_total=tithe_kept_total,
                         tithe_unkept_total=tithe_unkept_total)

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
                # Ensure tithe_kept column exists and is string type
                if 'tithe_kept' not in df.columns:
                    df['tithe_kept'] = 'False'
                # Convert column to string type to avoid dtype issues
                df['tithe_kept'] = df['tithe_kept'].astype(str)
                # Convert boolean to string for Google Sheets compatibility
                df.at[item_id, 'tithe_kept'] = 'True' if tithe_kept else 'False'
                connector.write_to_sheets(df, SOLD_ITEMS_SHEET_URL)
                logger.info(f"Updated tithe status for item {item_id} to {df.at[item_id, 'tithe_kept']}")
        
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
            if df.empty:
                invoices = []
            else:
                # Group by invoice_number to reconstruct invoice structure
                invoices_dict = {}
                for _, row in df.iterrows():
                    invoice_num = row.get('invoice_number', '')
                    if invoice_num not in invoices_dict:
                        invoices_dict[invoice_num] = {
                            'invoice_number': invoice_num,
                            'customer_name': row.get('customer_name', ''),
                            'products_summary': row.get('products_summary', ''),
                            'shipment_fee': row.get('shipment_fee', 0),
                            'total_amount': row.get('total_amount', 0),
                            'invoice_date': row.get('invoice_date', ''),
                            'created_at': row.get('created_at', ''),
                            'items_parsed': []
                        }
                    # Collect items for modal view
                    product_name = row.get('product_name', '')
                    if product_name:
                        invoices_dict[invoice_num]['items_parsed'].append({
                            'name': product_name,
                            'price': float(row.get('price_sold', 0)),
                            'quantity': int(row.get('quantity', 0)),
                            'subtotal': float(row.get('line_total', 0))
                        })
                invoices = list(invoices_dict.values())
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

@app.route('/api/create_invoice', methods=['POST'])
def create_invoice():
    """Create a new invoice"""
    try:
        data = request.json
        customer_name = data.get('customer_name')
        items = data.get('items', [])
        shipment_fee = float(data.get('shipment_fee', 0))
        total_amount = float(data.get('total_amount', 0))
        invoice_date = data.get('invoice_date', datetime.now().strftime('%Y-%m-%d'))
        
        invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{len(items)}"
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Generate products summary string
        products_summary_parts = []
        for item in items:
            product_name = item.get('name', 'N/A')
            quantity = item.get('quantity', 0)
            price = item.get('price', 0)
            subtotal = item.get('subtotal', 0)
            products_summary_parts.append(f"{product_name} ({quantity} pcs × ₱{price:.2f}) = ₱{subtotal:.2f}")
        products_summary = "; ".join(products_summary_parts) if products_summary_parts else "No items"
        
        # Create one row per product
        invoice_rows = []
        for item in items:
            invoice_row = {
                'invoice_number': invoice_number,
                'customer_name': customer_name,
                'products_summary': products_summary,
                'product_name': item.get('name', 'N/A'),
                'price_sold': item.get('price', 0),
                'quantity': item.get('quantity', 0),
                'line_total': item.get('subtotal', 0),
                'shipment_fee': shipment_fee,
                'total_amount': total_amount,
                'invoice_date': invoice_date,
                'created_at': created_at
            }
            invoice_rows.append(invoice_row)
        
        # If no items, create one row with empty product
        if not invoice_rows:
            invoice_row = {
                'invoice_number': invoice_number,
                'customer_name': customer_name,
                'products_summary': 'No items',
                'product_name': '',
                'price_sold': 0,
                'quantity': 0,
                'line_total': 0,
                'shipment_fee': shipment_fee,
                'total_amount': total_amount,
                'invoice_date': invoice_date,
                'created_at': created_at
            }
            invoice_rows.append(invoice_row)
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            # Handle empty DataFrame
            if df.empty:
                df = pd.DataFrame(columns=['invoice_number', 'customer_name', 'products_summary', 'product_name', 'price_sold', 'quantity', 'line_total', 'shipment_fee', 'total_amount', 'invoice_date', 'created_at'])
            new_invoice_df = pd.DataFrame(invoice_rows)
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

@app.route('/api/delete_invoice', methods=['POST'])
def delete_invoice():
    """Delete an invoice"""
    try:
        data = request.json
        invoice_number = data.get('invoice_number')
        
        if not invoice_number:
            return jsonify({'success': False, 'message': 'Invoice number is required'}), 400
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            if df.empty:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            # Find and remove the invoice
            initial_count = len(df)
            df = df[df['invoice_number'] != invoice_number]
            
            if len(df) == initial_count:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            connector.write_to_sheets(df, INVOICES_SHEET_URL)
            logger.info(f"Deleted invoice {invoice_number}")
        
        return jsonify({'success': True, 'message': 'Invoice deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting invoice: {str(e)}", exc_info=True)
        user_message = "Failed to delete invoice. Please try again."
        if "Google Sheets client not initialized" in str(e):
            user_message = "Unable to connect to Google Sheets. Please check your credentials."
        return jsonify({'success': False, 'message': user_message}), 400

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    
    # Get port from environment (Railway sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    # Debug mode only in development (not production)
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

