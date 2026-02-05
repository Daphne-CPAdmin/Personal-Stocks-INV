"""
Component to update Google Sheets with correct column structure
Updates all tabs with the new field names and structure
"""
import pandas as pd
import logging
from datetime import datetime
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_sources import DataConnector

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

def update_spreadsheet_structure(spreadsheet_url):
    """Update spreadsheet with correct column structure for all tabs"""
    connector = DataConnector({})
    
    logger.info("="*50)
    logger.info("STARTING: Update Spreadsheet Structure")
    logger.info(f"SPREADSHEET: {spreadsheet_url}")
    
    # Extract spreadsheet ID
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(spreadsheet_url)
    path_parts = parsed.path.split('/')
    spreadsheet_id = None
    for i, part in enumerate(path_parts):
        if part == 'd' and i + 1 < len(path_parts):
            spreadsheet_id = path_parts[i + 1]
            break
    
    if not spreadsheet_id:
        raise ValueError("Could not extract spreadsheet ID from URL")
    
    if not connector.client:
        raise ValueError("Google Sheets client not initialized. Please check your GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON in .env file")
    
    spreadsheet = connector.client.open_by_key(spreadsheet_id)
    
    # Define column structures for each tab
    tab_structures = {
        'Inventory': [
            'product_name', 'total_price', 'shipping_admin_fee', 'total_cost_per_unit', 
            'quantity', 'total_bought_quantity', 'remaining_qty', 'status', 'remarks', 
            'date_added', 'selling_price', 'profit', 'tithe', 'profit_after_tithe', 'date_sold'
        ],
        'Sold Items': [
            'product_name', 'quantity', 'total_cost_per_unit', 'selling_price', 
            'total_cost', 'profit', 'tithe', 'profit_after_tithe', 'tithe_kept', 
            'remarks', 'date_sold'
        ],
        'Invoices': [
            'invoice_number', 'customer_name', 'items', 'total_amount', 
            'invoice_date', 'created_at'
        ],
        'Customers': [
            'customer_name', 'total_orders', 'total_spent', 'first_order_date', 
            'last_order_date', 'products_purchased'
        ],
        'INDEX': [
            'product_name'  # Column A - product names
        ],
        'Used Freebie': [
            'product_name', 'quantity', 'total_cost_per_unit', 'status', 'remarks', 'date_used'
        ]
    }
    
    # Update each worksheet
    worksheets = spreadsheet.worksheets()
    updated_tabs = []
    
    for worksheet in worksheets:
        tab_name = worksheet.title
        logger.info(f"Processing tab: {tab_name}")
        
        if tab_name in tab_structures:
            # Get current data
            try:
                current_data = worksheet.get_all_records()
                current_df = pd.DataFrame(current_data) if current_data else pd.DataFrame()
                
                # Create new DataFrame with correct columns
                new_columns = tab_structures[tab_name]
                new_df = pd.DataFrame(columns=new_columns)
                
                # Map old columns to new columns if they exist
                if not current_df.empty:
                    column_mapping = {}
                    # Special mappings for renamed columns
                    old_to_new = {
                        'base_price': 'total_price',
                        'procurement_fees': 'shipping_admin_fee'
                    }
                    
                    for new_col in new_columns:
                        # Check for direct name match
                        found = False
                        for old_col in current_df.columns:
                            if old_col.lower() == new_col.lower():
                                column_mapping[new_col] = old_col
                                found = True
                                break
                        
                        # Check for renamed columns
                        if not found:
                            for old_col, mapped_new_col in old_to_new.items():
                                if mapped_new_col == new_col and old_col in current_df.columns:
                                    column_mapping[new_col] = old_col
                                    found = True
                                    break
                    
                    # Copy data from old columns to new columns
                    for new_col in new_columns:
                        if new_col in column_mapping:
                            old_col = column_mapping[new_col]
                            new_df[new_col] = current_df[old_col].values if old_col in current_df.columns else None
                        else:
                            new_df[new_col] = None
                    
                    logger.info(f"  Mapped {len(column_mapping)} columns from old structure")
                    logger.info(f"  Preserved {len(current_df)} rows of data")
                else:
                    logger.info(f"  Tab is empty, creating headers only")
                
                # Write updated structure
                worksheet.clear()
                worksheet.append_row(new_columns)
                
                # Write data rows if any
                if not new_df.empty:
                    for _, row in new_df.iterrows():
                        values = [str(val) if pd.notna(val) else '' for val in row.values]
                        worksheet.append_row(values)
                
                updated_tabs.append(tab_name)
                logger.info(f"  ✓ Updated {tab_name} with {len(new_columns)} columns")
                
            except Exception as e:
                logger.error(f"  ✗ Error updating {tab_name}: {str(e)}")
        else:
            logger.warning(f"  Tab '{tab_name}' not in structure definition, skipping")
    
    logger.info(f"SUMMARY: Updated {len(updated_tabs)} tabs: {', '.join(updated_tabs)}")
    logger.info("COMPLETED: Update Spreadsheet Structure")
    logger.info("="*50)
    
    return True

if __name__ == '__main__':
    # Get spreadsheet URL from command line or use default
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = 'https://docs.google.com/spreadsheets/d/1QpTtcPoTYgd1J9oDi0X1xuS-E5GPiuD1zto0Ger7JCQ/edit?gid=0#gid=0'
    
    update_spreadsheet_structure(url)

