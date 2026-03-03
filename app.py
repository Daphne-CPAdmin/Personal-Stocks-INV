from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import pandas as pd
import json
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

INVOICE_REQUIRED_COLUMNS = [
    'invoice_number', 'customer_name', 'products_summary', 'product_name', 'price_sold',
    'quantity', 'line_total', 'shipment_fee', 'total_amount', 'invoice_date', 'created_at',
    'fulfilled', 'paid', 'amount_paid', 'payment_reference', 'payment_history'
]

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

def _generate_invoice_number(existing_df):
    """Generate unique invoice number in INV-YYYYMMDD-XXX format."""
    date_prefix = datetime.now().strftime('%Y%m%d')
    base_prefix = f"INV-{date_prefix}-"
    next_seq = 1

    try:
        if existing_df is not None and not existing_df.empty and 'invoice_number' in existing_df.columns:
            for value in existing_df['invoice_number'].dropna().astype(str):
                value = value.strip()
                if value.startswith(base_prefix):
                    suffix = value.replace(base_prefix, '', 1)
                    if suffix.isdigit():
                        next_seq = max(next_seq, int(suffix) + 1)
    except Exception as e:
        logger.warning(f"Could not inspect existing invoice numbers: {str(e)}")

    return f"{base_prefix}{next_seq:03d}"

def _build_invoice_mask(df, invoice_number=None, created_at=None):
    """Build a safe mask for targeting a single logical invoice instance."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    if invoice_number:
        number_mask = df['invoice_number'].astype(str).str.strip() == str(invoice_number).strip()
        if created_at and 'created_at' in df.columns:
            created_mask = df['created_at'].astype(str).str.strip() == str(created_at).strip()
            combined = number_mask & created_mask
            return combined
        return number_mask

    return pd.Series([False] * len(df), index=df.index)

def _count_invoice_instances(df_subset):
    """Estimate how many distinct invoice instances exist in a subset."""
    if df_subset is None or df_subset.empty:
        return 0
    cols = ['created_at', 'customer_name', 'invoice_date', 'total_amount']
    available = [c for c in cols if c in df_subset.columns]
    if not available:
        return 0
    sig = df_subset[available].fillna('').astype(str).agg('|'.join, axis=1)
    return sig.nunique()


def _to_float(value, default=0.0):
    """Convert mixed values to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_payment_history(value):
    """Parse payment history JSON safely and normalize entry fields."""
    import ast
    import json

    history = []
    if isinstance(value, list):
        history = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                history = parsed
        except (ValueError, TypeError):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    history = parsed
            except (ValueError, SyntaxError, TypeError):
                history = []

    normalized = []
    for item in history:
        if not isinstance(item, dict):
            continue
        amount = _to_float(item.get('amount', 0))
        if amount <= 0:
            continue
        normalized.append({
            'amount': amount,
            'reference': str(item.get('reference', '') or '').strip(),
            'timestamp': str(item.get('timestamp', '') or '').strip()
        })
    return normalized


def _normalize_invoice_boolean_columns(df):
    """Keep invoice boolean fields as string values for Sheets compatibility."""
    bool_cols = ['paid', 'fulfilled']
    truthy = {'true', '1', 'yes'}
    for col in bool_cols:
        if col not in df.columns:
            continue
        df[col] = df[col].apply(
            lambda v: 'True' if str(v).strip().lower() in truthy else 'False'
        )
    return df


def _invoice_sync_marker(invoice_number, created_at):
    """Build stable marker prefix used in sold remarks for invoice-linked rows."""
    return f"INV_SYNC:{str(invoice_number).strip()}|{str(created_at).strip()}|"


def _safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure_inventory_columns(df):
    required = ['product_name', 'total_cost_per_unit', 'quantity', 'total_bought_quantity', 'remaining_qty', 'status', 'date_sold']
    if df is None or df.empty:
        df = pd.DataFrame(columns=required)
    for col in required:
        if col not in df.columns:
            if col in ['product_name', 'status', 'date_sold']:
                df[col] = ''
            else:
                df[col] = 0
    return df


def _ensure_sold_columns(df):
    required = ['product_name', 'quantity', 'total_cost_per_unit', 'selling_price', 'total_cost', 'profit', 'tithe', 'profit_after_tithe', 'tithe_kept', 'remarks', 'date_sold']
    if df is None or df.empty:
        df = pd.DataFrame(columns=required)
    for col in required:
        if col not in df.columns:
            if col in ['product_name', 'remarks', 'date_sold', 'tithe_kept']:
                df[col] = ''
            else:
                df[col] = 0
    if 'tithe_kept' in df.columns:
        df['tithe_kept'] = df['tithe_kept'].astype(str)
    return df


def _rollback_invoice_stock_sync(inventory_df, sold_df, invoice_number, created_at):
    """Restore inventory and remove sold rows linked to a specific invoice."""
    marker = _invoice_sync_marker(invoice_number, created_at)
    if sold_df.empty:
        return inventory_df, sold_df

    restore_rows = sold_df[sold_df['remarks'].astype(str).str.startswith(marker, na=False)]
    if restore_rows.empty:
        return inventory_df, sold_df

    for _, sold_row in restore_rows.iterrows():
        product_name = str(sold_row.get('product_name', '')).strip()
        qty = _safe_int(sold_row.get('quantity', 0), 0)
        if qty <= 0 or not product_name:
            continue
        candidate_idx = inventory_df[inventory_df['product_name'].astype(str).str.strip() == product_name].index
        if len(candidate_idx) == 0:
            continue
        # Restore to first matching row to keep stock totals accurate.
        idx = candidate_idx[0]
        current_remaining = _safe_int(inventory_df.at[idx, 'remaining_qty'], 0)
        inventory_df.at[idx, 'remaining_qty'] = current_remaining + qty
        inventory_df.at[idx, 'quantity'] = inventory_df.at[idx, 'remaining_qty']
        inventory_df.at[idx, 'status'] = 'in_stock' if _safe_float(inventory_df.at[idx, 'remaining_qty'], 0) > 0 else 'out_of_stock'

    sold_df = sold_df[~sold_df['remarks'].astype(str).str.startswith(marker, na=False)].reset_index(drop=True)
    return inventory_df, sold_df


def _apply_invoice_stock_sync(inventory_df, sold_df, invoice_number, created_at, items, invoice_date):
    """Consume inventory for invoice items and append corresponding sold rows."""
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sold_rows = []

    # Validate stock availability per product first.
    required_by_product = {}
    for item in items:
        name = str(item.get('name', '')).strip()
        qty = _safe_int(item.get('quantity', 0), 0)
        if name and qty > 0:
            required_by_product[name] = required_by_product.get(name, 0) + qty

    for product_name, needed_qty in required_by_product.items():
        product_rows = inventory_df[inventory_df['product_name'].astype(str).str.strip() == product_name]
        available = product_rows['remaining_qty'].apply(lambda v: _safe_int(v, 0)).sum() if not product_rows.empty else 0
        if available < needed_qty:
            raise ValueError(f"Insufficient stock for '{product_name}'. Needed {needed_qty}, available {available}.")

    marker = _invoice_sync_marker(invoice_number, created_at)
    for item in items:
        product_name = str(item.get('name', '')).strip()
        qty_to_consume = _safe_int(item.get('quantity', 0), 0)
        unit_price = _safe_float(item.get('price', 0), 0.0)
        if not product_name or qty_to_consume <= 0:
            continue

        candidate_idx = inventory_df[inventory_df['product_name'].astype(str).str.strip() == product_name].index.tolist()
        for idx in candidate_idx:
            if qty_to_consume <= 0:
                break
            available = _safe_int(inventory_df.at[idx, 'remaining_qty'], 0)
            if available <= 0:
                continue
            consume = min(available, qty_to_consume)
            inventory_df.at[idx, 'remaining_qty'] = available - consume
            inventory_df.at[idx, 'quantity'] = inventory_df.at[idx, 'remaining_qty']
            inventory_df.at[idx, 'status'] = 'in_stock' if _safe_float(inventory_df.at[idx, 'remaining_qty'], 0) > 0 else 'out_of_stock'
            inventory_df.at[idx, 'date_sold'] = invoice_date or now_ts

            cost_per_unit = _safe_float(inventory_df.at[idx, 'total_cost_per_unit'], 0.0)
            line_revenue = unit_price * consume
            total_cost = cost_per_unit * consume
            profit = line_revenue - total_cost
            tithe = profit * 0.10
            sold_rows.append({
                'product_name': product_name,
                'quantity': consume,
                'total_cost_per_unit': cost_per_unit,
                'selling_price': line_revenue,
                'total_cost': total_cost,
                'profit': profit,
                'tithe': tithe,
                'profit_after_tithe': profit - tithe,
                'tithe_kept': 'False',
                'remarks': f"{marker}line:{product_name}",
                'date_sold': invoice_date or now_ts
            })
            qty_to_consume -= consume

    if sold_rows:
        sold_df = pd.concat([sold_df, pd.DataFrame(sold_rows)], ignore_index=True)
    if 'tithe_kept' in sold_df.columns:
        sold_df['tithe_kept'] = sold_df['tithe_kept'].astype(str)
    return inventory_df, sold_df


def _sync_invoice_with_inventory_and_sold(invoice_number, created_at, items, invoice_date, replace_existing=False, delete_only=False):
    """Synchronize invoice quantities to inventory and sold sheets."""
    if not INVENTORY_SHEET_URL or not SOLD_ITEMS_SHEET_URL:
        return

    inventory_df = _ensure_inventory_columns(connector.read_from_sheets(INVENTORY_SHEET_URL))
    sold_df = _ensure_sold_columns(connector.read_from_sheets(SOLD_ITEMS_SHEET_URL))

    if replace_existing or delete_only:
        inventory_df, sold_df = _rollback_invoice_stock_sync(
            inventory_df=inventory_df,
            sold_df=sold_df,
            invoice_number=invoice_number,
            created_at=created_at
        )

    if not delete_only:
        inventory_df, sold_df = _apply_invoice_stock_sync(
            inventory_df=inventory_df,
            sold_df=sold_df,
            invoice_number=invoice_number,
            created_at=created_at,
            items=items,
            invoice_date=invoice_date
        )

    connector.write_to_sheets(inventory_df, INVENTORY_SHEET_URL)
    connector.write_to_sheets(sold_df, SOLD_ITEMS_SHEET_URL)


def _reset_inventory_from_totals(inventory_df):
    """Reset inventory remaining/quantity from total bought before replay."""
    inventory_df = _ensure_inventory_columns(inventory_df)
    for idx in inventory_df.index:
        base_qty = _safe_int(
            inventory_df.at[idx, 'total_bought_quantity']
            if 'total_bought_quantity' in inventory_df.columns
            else inventory_df.at[idx, 'quantity'],
            0
        )
        inventory_df.at[idx, 'remaining_qty'] = max(0, base_qty)
        inventory_df.at[idx, 'quantity'] = max(0, base_qty)
        inventory_df.at[idx, 'status'] = 'in_stock' if base_qty > 0 else 'out_of_stock'
        if 'date_sold' in inventory_df.columns:
            inventory_df.at[idx, 'date_sold'] = ''
    return inventory_df


def _rebuild_invoice_inventory_sold_sync():
    """Backtrack from current invoices to rebuild inventory and sold sheets."""
    if not INVENTORY_SHEET_URL or not SOLD_ITEMS_SHEET_URL or not INVOICES_SHEET_URL:
        raise ValueError("Inventory, Sold Items, and Invoices sheet URLs must be configured.")

    inventory_df = _reset_inventory_from_totals(connector.read_from_sheets(INVENTORY_SHEET_URL))
    sold_df = _ensure_sold_columns(connector.read_from_sheets(SOLD_ITEMS_SHEET_URL))
    invoice_df = connector.read_from_sheets(INVOICES_SHEET_URL)

    # Keep non-invoice-linked sold rows; rebuild invoice-linked rows from scratch.
    sold_df = sold_df[~sold_df['remarks'].astype(str).str.startswith('INV_SYNC:', na=False)].reset_index(drop=True)

    replayed_rows = 0
    skipped_rows = []
    if invoice_df is not None and not invoice_df.empty:
        replay_df = invoice_df.copy()
        replay_df['_sort_dt'] = pd.to_datetime(
            replay_df.get('created_at', replay_df.get('invoice_date', '')),
            errors='coerce'
        )
        replay_df = replay_df.sort_values('_sort_dt', na_position='last')

        for _, row in replay_df.iterrows():
            product_name = str(row.get('product_name', '')).strip()
            quantity = _safe_int(row.get('quantity', 0), 0)
            price_sold = _safe_float(row.get('price_sold', 0), 0.0)
            invoice_number = str(row.get('invoice_number', '')).strip()
            created_at = str(row.get('created_at', '')).strip()
            invoice_date = str(row.get('invoice_date', '')).strip()

            if not product_name or quantity <= 0 or not invoice_number:
                continue

            try:
                inventory_df, sold_df = _apply_invoice_stock_sync(
                    inventory_df=inventory_df,
                    sold_df=sold_df,
                    invoice_number=invoice_number,
                    created_at=created_at,
                    items=[{
                        'name': product_name,
                        'quantity': quantity,
                        'price': price_sold
                    }],
                    invoice_date=invoice_date
                )
                replayed_rows += 1
            except Exception as e:
                skipped_rows.append(
                    f"{invoice_number} / {product_name} / qty {quantity}: {str(e)}"
                )

    connector.write_to_sheets(inventory_df, INVENTORY_SHEET_URL)
    connector.write_to_sheets(sold_df, SOLD_ITEMS_SHEET_URL)
    return {
        'replayed_rows': replayed_rows,
        'skipped_rows': skipped_rows,
        'sold_rows_total': len(sold_df),
        'inventory_rows_total': len(inventory_df)
    }

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
                
                # Store original index before sorting
                df['original_index'] = df.index
                
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
                        if col == 'status':
                            df[col] = 'in_stock'  # Default status as string
                        elif col in ['remarks', 'supplier', 'date_sold']:
                            df[col] = None
                        else:
                            df[col] = 0
                
                # Calculate status based on remaining_qty (in_stock or out_of_stock)
                if 'remaining_qty' in df.columns:
                    df['status'] = df['remaining_qty'].apply(lambda x: 'in_stock' if (pd.notna(x) and float(x) > 0) else 'out_of_stock')
                else:
                    df['status'] = 'out_of_stock'
                
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
                            'total_bought': 0,
                            'total_remaining': 0,
                            'entry_count': 0
                        }
                    # Safely convert quantities - use total_bought_quantity instead of quantity
                    try:
                        total_bought_val = item.get('total_bought_quantity', item.get('quantity', 0))
                        remaining_val = item.get('remaining_qty', total_bought_val)
                        total_bought = int(float(str(total_bought_val))) if total_bought_val else 0
                        remaining = int(float(str(remaining_val))) if remaining_val else 0
                    except (ValueError, TypeError):
                        total_bought = 0
                        remaining = 0
                    product_summary[product_name]['total_bought'] += total_bought
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
                    'total_bought': 0,
                    'total_remaining': 0,
                    'entry_count': 0
                }
            # Safely convert quantities - use total_bought_quantity instead of quantity
            try:
                total_bought_val = item.get('total_bought_quantity', item.get('quantity', 0))
                remaining_val = item.get('remaining_qty', total_bought_val)
                total_bought = int(float(str(total_bought_val))) if total_bought_val else 0
                remaining = int(float(str(remaining_val))) if remaining_val else 0
            except (ValueError, TypeError):
                total_bought = 0
                remaining = 0
            product_summary[product_name]['total_bought'] += total_bought
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
            
            # Validate product_id is within bounds (product_id is the original DataFrame index)
            if df.empty:
                return jsonify({'success': False, 'message': 'Inventory is empty. Please refresh the page and try again.'}), 400
            
            # Find the row by original_index column (stored before sorting)
            if 'original_index' in df.columns:
                # Convert product_id to same type as original_index for comparison
                matching_rows = df[df['original_index'].astype(int) == int(product_id)]
                if matching_rows.empty:
                    logger.error(f"Product with original_index {product_id} not found. Available indices: {df['original_index'].tolist()}")
                    return jsonify({'success': False, 'message': 'Product not found. Please refresh the page and try again.'}), 400
                # Get the actual DataFrame index of the matching row
                actual_index = matching_rows.index[0]
                logger.info(f"Found product: original_index={product_id}, actual_index={actual_index}, product_name={df.at[actual_index, 'product_name']}")
            else:
                # Fallback: use product_id as direct index (for backward compatibility)
                if product_id < 0 or product_id >= len(df):
                    return jsonify({'success': False, 'message': 'Product not found. Please refresh the page and try again.'}), 400
                actual_index = product_id
                logger.info(f"Using fallback: product_id={product_id}, product_name={df.at[actual_index, 'product_name']}")
            
            # Use actual_index for all DataFrame operations
            product_id = actual_index
            
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
            
            # Decrement remaining_qty if action consumes stock.
            if new_status in ['sold', 'used', 'freebie', 'raffled']:
                new_remaining = max(0, current_remaining - quantity_used)
                # Ensure remaining_qty column exists
                if 'remaining_qty' not in df.columns:
                    df['remaining_qty'] = current_remaining
                df.at[product_id, 'remaining_qty'] = new_remaining
                # Update quantity to reflect remaining (if column exists)
                if 'quantity' in df.columns:
                    df.at[product_id, 'quantity'] = new_remaining
            
            # Track status history
            import json
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            status_history_entry = {
                'status': new_status,
                'timestamp': current_timestamp,
                'remarks': remarks,
                'quantity_used': quantity_used
            }
            
            # Get existing status history or initialize empty list
            if 'status_history' not in df.columns:
                df['status_history'] = ''
            
            existing_history = df.at[product_id, 'status_history']
            if pd.isna(existing_history) or existing_history == '' or existing_history == 'nan':
                history_list = []
            else:
                try:
                    # Try to parse as JSON string
                    if isinstance(existing_history, str):
                        history_list = json.loads(existing_history)
                    else:
                        history_list = existing_history if isinstance(existing_history, list) else []
                except (json.JSONDecodeError, ValueError, TypeError):
                    history_list = []
            
            # Add new entry to history
            history_list.append(status_history_entry)
            
            # Store history as JSON string
            df.at[product_id, 'status_history'] = json.dumps(history_list)
            
            # Update current status - don't store action status, calculate from remaining_qty
            # Status will be calculated as "in_stock" or "out_of_stock" based on remaining_qty
            # We still track the action (sold/used/freebie/raffled) in status_history
            # But the status column should reflect stock availability
            # Don't update status column here - it will be calculated based on remaining_qty
            df.at[product_id, 'remarks'] = remarks
            
            # Keep stored status aligned immediately after update as well.
            current_remaining_after = safe_int(df.at[product_id, 'remaining_qty'], 0)
            df.at[product_id, 'status'] = 'in_stock' if current_remaining_after > 0 else 'out_of_stock'

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
            if not df.empty:
                # Keep original row index so edit actions update correct sheet row.
                df = df.reset_index(drop=False).rename(columns={'index': 'row_index'})
                used_items = df.to_dict('records')
            else:
                used_items = []
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

@app.route('/api/update_used_freebie_item', methods=['POST'])
def update_used_freebie_item():
    """Update used/freebie item details."""
    try:
        data = request.json or {}
        row_index = int(data.get('row_index'))
        status = str(data.get('status', '')).strip().lower()
        quantity = int(float(data.get('quantity', 0) or 0))
        total_cost_per_unit = float(data.get('total_cost_per_unit', 0) or 0)
        remarks = str(data.get('remarks', '') or '')

        if status not in ['used', 'freebie']:
            return jsonify({'success': False, 'message': 'Status must be used or freebie'}), 400
        if quantity <= 0:
            return jsonify({'success': False, 'message': 'Quantity must be greater than zero'}), 400
        if total_cost_per_unit < 0:
            return jsonify({'success': False, 'message': 'Cost per unit cannot be negative'}), 400
        if not USED_FREEBIE_SHEET_URL:
            return jsonify({'success': False, 'message': 'Used/Freebie sheet is not configured'}), 400

        df = connector.read_from_sheets(USED_FREEBIE_SHEET_URL)
        if df.empty or row_index < 0 or row_index >= len(df):
            return jsonify({'success': False, 'message': 'Item not found'}), 404

        df.at[row_index, 'status'] = status
        df.at[row_index, 'quantity'] = quantity
        df.at[row_index, 'total_cost_per_unit'] = total_cost_per_unit
        df.at[row_index, 'remarks'] = remarks

        if 'date_used' in df.columns:
            df.at[row_index, 'date_used'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        connector.write_to_sheets(df, USED_FREEBIE_SHEET_URL)
        logger.info(f"Updated used/freebie row {row_index} -> {status}")
        return jsonify({'success': True, 'message': 'Item updated successfully'})
    except Exception as e:
        logger.error(f"Error updating used/freebie item: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400

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
                # Group by invoice_number + created_at to separate same-day collisions safely.
                invoices_dict = {}
                for row_idx, row in df.iterrows():
                    invoice_num = str(row.get('invoice_number', '')).strip()
                    created_at = str(row.get('created_at', '')).strip()
                    group_key = f"{invoice_num}__{created_at if created_at else row_idx}"

                    if group_key not in invoices_dict:
                        # Handle boolean conversion for paid/fulfilled (may come as string from sheets)
                        paid_val = row.get('paid', False)
                        if isinstance(paid_val, str):
                            paid_val = paid_val.lower() in ['true', '1', 'yes']
                        fulfilled_val = row.get('fulfilled', False)
                        if isinstance(fulfilled_val, str):
                            fulfilled_val = fulfilled_val.lower() in ['true', '1', 'yes']
                        
                        invoices_dict[group_key] = {
                            'invoice_number': invoice_num,
                            'customer_name': row.get('customer_name', ''),
                            'products_summary': row.get('products_summary', ''),
                            'shipment_fee': row.get('shipment_fee', 0),
                            'total_amount': row.get('total_amount', 0),
                            'invoice_date': row.get('invoice_date', ''),
                            'created_at': row.get('created_at', ''),
                            'paid': bool(paid_val),
                            'fulfilled': bool(fulfilled_val),
                            'amount_paid': _to_float(row.get('amount_paid', 0)),
                            'payment_reference': str(row.get('payment_reference', '') or '').strip(),
                            'payment_history': _parse_payment_history(row.get('payment_history', '[]')),
                            'items_parsed': []
                        }
                    # Collect items for modal view
                    product_name = str(row.get('product_name', '')).strip()
                    price_sold = row.get('price_sold', 0)
                    quantity = row.get('quantity', 0)
                    line_total = row.get('line_total', 0)
                    
                    # Only add if product_name exists and is not empty
                    if product_name and product_name.lower() not in ['', 'nan', 'none', 'n/a']:
                        try:
                            # Ensure numeric values are properly converted
                            price_val = float(price_sold) if price_sold else 0
                            qty_val = int(quantity) if quantity else 0
                            subtotal_val = float(line_total) if line_total else (price_val * qty_val)
                            
                            invoices_dict[group_key]['items_parsed'].append({
                                'name': product_name,
                                'price': price_val,
                                'quantity': qty_val,
                                'subtotal': subtotal_val
                            })
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Error parsing invoice item for {invoice_num}: {str(e)}")
                            # Still add the item with default values
                            invoices_dict[group_key]['items_parsed'].append({
                                'name': product_name,
                                'price': 0,
                                'quantity': 0,
                                'subtotal': 0
                            })
                invoices = list(invoices_dict.values())

                # Show most recent invoices first.
                def _sort_invoice_key(inv):
                    created_at = inv.get('created_at', '')
                    invoice_date = inv.get('invoice_date', '')
                    dt = pd.to_datetime(created_at, errors='coerce')
                    if pd.isna(dt):
                        dt = pd.to_datetime(invoice_date, errors='coerce')
                    if pd.isna(dt):
                        return datetime.min
                    return dt.to_pydatetime()

                invoices = sorted(invoices, key=_sort_invoice_key, reverse=True)
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
        import json
        data = request.json
        customer_name = data.get('customer_name')
        items = data.get('items', [])
        shipment_fee = float(data.get('shipment_fee', 0))
        total_amount = float(data.get('total_amount', 0))
        amount_paid = _to_float(data.get('amount_paid', 0))
        payment_reference = str(data.get('payment_reference', '') or '').strip()
        invoice_date = data.get('invoice_date', datetime.now().strftime('%Y-%m-%d'))
        amount_paid = max(0.0, min(amount_paid, total_amount))
        is_paid = amount_paid >= total_amount and total_amount > 0
        initial_payment_history = []
        if amount_paid > 0:
            initial_payment_history.append({
                'amount': amount_paid,
                'reference': payment_reference,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        
        invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{datetime.now().strftime('%H%M%S')}"
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
                'created_at': created_at,
                'paid': is_paid,
                'fulfilled': False,
                'amount_paid': amount_paid,
                'payment_reference': payment_reference,
                'payment_history': json.dumps(initial_payment_history)
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
                'created_at': created_at,
                'paid': is_paid,
                'fulfilled': False,
                'amount_paid': amount_paid,
                'payment_reference': payment_reference,
                'payment_history': json.dumps(initial_payment_history)
            }
            invoice_rows.append(invoice_row)
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            invoice_number = _generate_invoice_number(df)
            # Reflect generated invoice number into rows before concat.
            for row in invoice_rows:
                row['invoice_number'] = invoice_number

            # Sync inventory + sold items from invoice lines before persisting invoice rows.
            sync_items = []
            for item in items:
                name = str(item.get('name', '')).strip()
                price = _safe_float(item.get('price', 0), 0.0)
                quantity = _safe_int(item.get('quantity', 0), 0)
                if name and quantity > 0:
                    sync_items.append({'name': name, 'price': price, 'quantity': quantity})
            _sync_invoice_with_inventory_and_sold(
                invoice_number=invoice_number,
                created_at=created_at,
                items=sync_items,
                invoice_date=invoice_date,
                replace_existing=False,
                delete_only=False
            )
            # Handle empty DataFrame
            if df.empty:
                df = pd.DataFrame(columns=INVOICE_REQUIRED_COLUMNS)

            # Keep exact invoices sheet schema/order requested by user.
            required_columns = INVOICE_REQUIRED_COLUMNS
            for col in required_columns:
                if col not in df.columns and col in ['fulfilled', 'paid']:
                    df[col] = 'False'
                elif col not in df.columns:
                    df[col] = ''
            df = df[required_columns]
            # Ensure paid and fulfilled columns exist
            if 'paid' not in df.columns:
                df['paid'] = False
            if 'fulfilled' not in df.columns:
                df['fulfilled'] = False
            new_invoice_df = pd.DataFrame(invoice_rows)
            df = pd.concat([df, new_invoice_df], ignore_index=True)
            df = _normalize_invoice_boolean_columns(df)
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

@app.route('/api/update_invoice_status', methods=['POST'])
def update_invoice_status():
    """Update invoice paid/fulfilled status"""
    try:
        data = request.json
        invoice_number = data.get('invoice_number')
        created_at = data.get('created_at')
        status_type = data.get('status_type')  # 'paid' or 'fulfilled'
        status_value = data.get('status_value', True)  # True/False
        
        if not invoice_number or not status_type:
            return jsonify({'success': False, 'message': 'Invoice reference and status type are required'}), 400
        
        if status_type not in ['paid', 'fulfilled']:
            return jsonify({'success': False, 'message': 'Status type must be "paid" or "fulfilled"'}), 400
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            if df.empty:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            # Ensure columns exist
            if status_type not in df.columns:
                df[status_type] = 'False'
            
            # Update all rows for the targeted invoice instance.
            mask = _build_invoice_mask(df, invoice_number=invoice_number, created_at=created_at)
            if not mask.any():
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404

            # Safety guard: prevent mass-updating multiple invoice instances.
            if not created_at:
                candidate_rows = df[df['invoice_number'].astype(str).str.strip() == str(invoice_number).strip()]
                if _count_invoice_instances(candidate_rows) > 1:
                    return jsonify({
                        'success': False,
                        'message': 'This invoice number matches multiple invoices. Please refresh and retry from the latest list.'
                    }), 409
            
            # Convert boolean properly
            if isinstance(status_value, str):
                status_value = status_value.lower() in ['true', '1', 'yes']
            
            df.loc[mask, status_type] = 'True' if bool(status_value) else 'False'
            df = _normalize_invoice_boolean_columns(df)
            connector.write_to_sheets(df, INVOICES_SHEET_URL)
            logger.info(f"Updated invoice {invoice_number} {status_type} status to {status_value}")
        
        return jsonify({'success': True, 'message': f'Invoice {status_type} status updated successfully'})
    except Exception as e:
        logger.error(f"Error updating invoice status: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/update_invoice', methods=['POST'])
def update_invoice():
    """Update an existing invoice and its line items."""
    try:
        import json
        data = request.json or {}
        invoice_number = data.get('invoice_number')
        created_at = data.get('created_at')
        customer_name = (data.get('customer_name') or '').strip()
        invoice_date = (data.get('invoice_date') or '').strip()
        shipment_fee = float(data.get('shipment_fee', 0) or 0)
        payload_amount_paid = data.get('amount_paid')
        payload_payment_reference = data.get('payment_reference')
        items = data.get('items', [])

        if not invoice_number:
            return jsonify({'success': False, 'message': 'Invoice reference is required'}), 400
        if not customer_name:
            return jsonify({'success': False, 'message': 'Customer name is required'}), 400
        if not invoice_date:
            return jsonify({'success': False, 'message': 'Invoice date is required'}), 400
        if not isinstance(items, list) or len(items) == 0:
            return jsonify({'success': False, 'message': 'At least one invoice item is required'}), 400

        normalized_items = []
        subtotal = 0.0
        for item in items:
            name = str(item.get('name', '')).strip()
            price = float(item.get('price', 0) or 0)
            quantity = int(float(item.get('quantity', 0) or 0))
            if not name or price <= 0 or quantity <= 0:
                continue
            line_total = float(item.get('subtotal', price * quantity) or (price * quantity))
            subtotal += line_total
            normalized_items.append({
                'name': name,
                'price': price,
                'quantity': quantity,
                'subtotal': line_total
            })

        if len(normalized_items) == 0:
            return jsonify({'success': False, 'message': 'No valid invoice items found'}), 400

        if not INVOICES_SHEET_URL:
            return jsonify({'success': False, 'message': 'Invoice sheet is not configured'}), 400

        df = connector.read_from_sheets(INVOICES_SHEET_URL)
        if df.empty:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404

        existing_mask = _build_invoice_mask(df, invoice_number=invoice_number, created_at=created_at)
        if not existing_mask.any():
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404

        # Safety guard: avoid replacing multiple distinct invoices when invoice_number collides.
        if not created_at:
            candidate_rows = df[df['invoice_number'].astype(str).str.strip() == str(invoice_number).strip()]
            if _count_invoice_instances(candidate_rows) > 1:
                return jsonify({
                    'success': False,
                    'message': 'This invoice number matches multiple invoices. Please refresh and edit the exact invoice entry again.'
                }), 409

        existing_rows = df[existing_mask]
        first_row = existing_rows.iloc[0]
        created_at = first_row.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        paid = first_row.get('paid', False)
        fulfilled = first_row.get('fulfilled', False)
        existing_amount_paid = _to_float(first_row.get('amount_paid', 0))
        existing_payment_reference = str(first_row.get('payment_reference', '') or '').strip()
        existing_payment_history = _parse_payment_history(first_row.get('payment_history', '[]'))

        if isinstance(paid, str):
            paid = paid.lower() in ['true', '1', 'yes']
        if isinstance(fulfilled, str):
            fulfilled = fulfilled.lower() in ['true', '1', 'yes']

        total_amount = subtotal + shipment_fee
        if payload_amount_paid is None:
            amount_paid = existing_amount_paid
        else:
            amount_paid = _to_float(payload_amount_paid, existing_amount_paid)
        amount_paid = max(0.0, min(amount_paid, total_amount))
        payment_reference = existing_payment_reference if payload_payment_reference is None else str(payload_payment_reference or '').strip()
        paid = bool(paid) or (amount_paid >= total_amount and total_amount > 0)
        if not existing_payment_history and amount_paid > 0:
            existing_payment_history.append({
                'amount': amount_paid,
                'reference': payment_reference,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        products_summary = "; ".join(
            f"{i['name']} ({i['quantity']} pcs x PHP {i['price']:.2f}) = PHP {i['subtotal']:.2f}"
            for i in normalized_items
        )

        # Sync inventory + sold sheets for this invoice edit by rollback + reapply.
        _sync_invoice_with_inventory_and_sold(
            invoice_number=invoice_number,
            created_at=created_at,
            items=normalized_items,
            invoice_date=invoice_date,
            replace_existing=True,
            delete_only=False
        )

        rebuilt_rows = []
        for item in normalized_items:
            rebuilt_rows.append({
                'invoice_number': invoice_number,
                'customer_name': customer_name,
                'products_summary': products_summary,
                'product_name': item['name'],
                'price_sold': item['price'],
                'quantity': item['quantity'],
                'line_total': item['subtotal'],
                'shipment_fee': shipment_fee,
                'total_amount': total_amount,
                'invoice_date': invoice_date,
                'created_at': created_at,
                'paid': bool(paid),
                'fulfilled': bool(fulfilled),
                'amount_paid': amount_paid,
                'payment_reference': payment_reference,
                'payment_history': json.dumps(existing_payment_history)
            })

        remaining_df = df[~existing_mask]
        updated_df = pd.concat([remaining_df, pd.DataFrame(rebuilt_rows)], ignore_index=True)
        # Keep exact invoices sheet schema/order requested by user.
        required_columns = INVOICE_REQUIRED_COLUMNS
        for col in required_columns:
            if col not in updated_df.columns and col in ['fulfilled', 'paid']:
                updated_df[col] = 'False'
            elif col not in updated_df.columns:
                updated_df[col] = ''
        updated_df = updated_df[required_columns]
        updated_df = _normalize_invoice_boolean_columns(updated_df)
        connector.write_to_sheets(updated_df, INVOICES_SHEET_URL)

        return jsonify({
            'success': True,
            'message': 'Invoice updated successfully',
            'invoice_number': invoice_number,
            'subtotal': subtotal,
            'total_amount': total_amount,
            'amount_paid': amount_paid,
            'balance_due': max(0.0, total_amount - amount_paid)
        })
    except Exception as e:
        logger.error(f"Error updating invoice: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/api/add_invoice_payment', methods=['POST'])
def add_invoice_payment():
    """Add payment to an invoice and update its outstanding balance."""
    try:
        import json
        data = request.json or {}
        invoice_number = data.get('invoice_number')
        created_at = data.get('created_at')
        payment_amount = _to_float(data.get('payment_amount', 0))
        payment_reference = str(data.get('payment_reference', '') or '').strip()

        if not invoice_number:
            return jsonify({'success': False, 'message': 'Invoice reference is required'}), 400
        if payment_amount <= 0:
            return jsonify({'success': False, 'message': 'Payment amount must be greater than zero'}), 400
        if not INVOICES_SHEET_URL:
            return jsonify({'success': False, 'message': 'Invoice sheet is not configured'}), 400

        df = connector.read_from_sheets(INVOICES_SHEET_URL)
        if df.empty:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404

        mask = _build_invoice_mask(df, invoice_number=invoice_number, created_at=created_at)
        if not mask.any():
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404

        # Safety guard: prevent cross-invoice updates for duplicate invoice numbers.
        if not created_at:
            candidate_rows = df[df['invoice_number'].astype(str).str.strip() == str(invoice_number).strip()]
            if _count_invoice_instances(candidate_rows) > 1:
                return jsonify({
                    'success': False,
                    'message': 'This invoice number matches multiple invoices. Please refresh and retry from the latest list.'
                }), 409

        if 'amount_paid' not in df.columns:
            df['amount_paid'] = 0.0
        if 'payment_reference' not in df.columns:
            df['payment_reference'] = ''
        if 'payment_history' not in df.columns:
            df['payment_history'] = '[]'

        first_row = df[mask].iloc[0]
        total_amount = _to_float(first_row.get('total_amount', 0))
        current_paid = _to_float(first_row.get('amount_paid', 0))
        payment_history = _parse_payment_history(first_row.get('payment_history', '[]'))
        updated_paid = min(total_amount, max(0.0, current_paid + payment_amount))
        balance_due = max(0.0, total_amount - updated_paid)
        is_paid = balance_due <= 0
        payment_history.append({
            'amount': payment_amount,
            'reference': payment_reference,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

        df.loc[mask, 'amount_paid'] = updated_paid
        if payment_reference:
            df.loc[mask, 'payment_reference'] = payment_reference
        df.loc[mask, 'payment_history'] = json.dumps(payment_history)
        df.loc[mask, 'paid'] = 'True' if bool(is_paid) else 'False'

        for col in INVOICE_REQUIRED_COLUMNS:
            if col not in df.columns and col in ['fulfilled', 'paid']:
                df[col] = 'False'
            elif col not in df.columns:
                df[col] = ''
        df = df[INVOICE_REQUIRED_COLUMNS]
        df = _normalize_invoice_boolean_columns(df)

        connector.write_to_sheets(df, INVOICES_SHEET_URL)
        return jsonify({
            'success': True,
            'message': 'Payment recorded successfully',
            'amount_paid': updated_paid,
            'balance_due': balance_due,
            'paid': bool(is_paid),
            'payment_history': payment_history
        })
    except Exception as e:
        logger.error(f"Error adding invoice payment: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/update_sold_item', methods=['POST'])
def update_sold_item():
    """Update a sold item (remarks, price, tithe kept)."""
    try:
        data = request.json or {}
        item_id = int(data.get('item_id'))
        remarks = data.get('remarks', '')
        tithe_kept = data.get('tithe_kept', None)
        selling_price = data.get('selling_price', None)

        if not SOLD_ITEMS_SHEET_URL:
            return jsonify({'success': False, 'message': 'Sold items sheet is not configured'}), 400

        df = connector.read_from_sheets(SOLD_ITEMS_SHEET_URL)
        if df.empty or item_id < 0 or item_id >= len(df):
            return jsonify({'success': False, 'message': 'Sold item not found'}), 404

        # Keep remarks editable.
        df.at[item_id, 'remarks'] = remarks

        # Keep tithe_kept editable.
        if tithe_kept is not None:
            if isinstance(tithe_kept, str):
                tithe_kept = tithe_kept.lower() in ['true', '1', 'yes']
            df.at[item_id, 'tithe_kept'] = 'True' if tithe_kept else 'False'

        # If selling price changes, recompute derived values.
        if selling_price is not None and str(selling_price) != '':
            selling_price = float(selling_price)
            quantity = int(float(df.at[item_id, 'quantity'])) if pd.notna(df.at[item_id, 'quantity']) else 0
            cost_per_unit = float(df.at[item_id, 'total_cost_per_unit']) if pd.notna(df.at[item_id, 'total_cost_per_unit']) else 0.0
            total_cost = cost_per_unit * quantity
            profit = selling_price - total_cost
            tithe = profit * 0.10
            profit_after_tithe = profit - tithe

            df.at[item_id, 'selling_price'] = selling_price
            df.at[item_id, 'total_cost'] = total_cost
            df.at[item_id, 'profit'] = profit
            df.at[item_id, 'tithe'] = tithe
            df.at[item_id, 'profit_after_tithe'] = profit_after_tithe

        connector.write_to_sheets(df, SOLD_ITEMS_SHEET_URL)
        return jsonify({'success': True, 'message': 'Sold item updated successfully'})
    except Exception as e:
        logger.error(f"Error updating sold item: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/delete_invoice', methods=['POST'])
def delete_invoice():
    """Delete an invoice"""
    try:
        data = request.json
        invoice_number = data.get('invoice_number')
        created_at = data.get('created_at')
        
        if not invoice_number:
            return jsonify({'success': False, 'message': 'Invoice number is required'}), 400
        
        if INVOICES_SHEET_URL:
            df = connector.read_from_sheets(INVOICES_SHEET_URL)
            if df.empty:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            # Find and remove only the targeted invoice instance.
            initial_count = len(df)
            delete_mask = _build_invoice_mask(df, invoice_number=invoice_number, created_at=created_at)
            if not delete_mask.any():
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404

            # Safety guard: avoid deleting multiple distinct invoices by shared number only.
            if not created_at:
                candidate_rows = df[df['invoice_number'].astype(str).str.strip() == str(invoice_number).strip()]
                if _count_invoice_instances(candidate_rows) > 1:
                    return jsonify({
                        'success': False,
                        'message': 'This invoice number matches multiple invoices. Please refresh and delete the exact invoice entry again.'
                    }), 409
                # Use the matched invoice's created_at for precise stock rollback.
                if not candidate_rows.empty and 'created_at' in candidate_rows.columns:
                    created_at = str(candidate_rows.iloc[0].get('created_at', '')).strip()

            # Roll back inventory and sold rows linked to this invoice.
            _sync_invoice_with_inventory_and_sold(
                invoice_number=invoice_number,
                created_at=created_at,
                items=[],
                invoice_date='',
                replace_existing=False,
                delete_only=True
            )

            df = df[~delete_mask]
            
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


@app.route('/api/rebuild_invoice_sync', methods=['POST'])
def rebuild_invoice_sync():
    """Rebuild inventory/sold data from current invoice rows."""
    try:
        result = _rebuild_invoice_inventory_sold_sync()
        message = f"Rebuild completed. Replayed {result['replayed_rows']} invoice rows."
        if result['skipped_rows']:
            message += f" Skipped {len(result['skipped_rows'])} rows due to stock mismatch."
        return jsonify({
            'success': True,
            'message': message,
            'result': result
        })
    except Exception as e:
        logger.error(f"Error rebuilding invoice sync: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 400

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    
    # Get port from environment (Railway sets this automatically)
    port = int(os.environ.get('PORT', 5000))
    # Debug mode only in development (not production)
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

