#!/usr/bin/env python3
"""
Setup verification script - tests Google Sheets connection and configuration
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=" * 60)
print("SETUP VERIFICATION")
print("=" * 60)

# Check environment variables
print("\n1. Checking environment variables...")
required_vars = {
    'INVENTORY_SHEET_URL': 'Inventory sheet URL',
    'SOLD_ITEMS_SHEET_URL': 'Sold Items sheet URL',
    'INVOICES_SHEET_URL': 'Invoices sheet URL',
    'CUSTOMERS_SHEET_URL': 'Customers sheet URL',
    'INDEX_SHEET_URL': 'INDEX sheet URL (product names)',
    'SECRET_KEY': 'Flask secret key'
}

optional_vars = {
    'GOOGLE_CREDENTIALS_PATH': 'Path to Google credentials JSON file',
    'GOOGLE_CREDENTIALS_JSON': 'Google credentials JSON (for Railway)'
}

all_good = True
for var, description in required_vars.items():
    value = os.getenv(var)
    if value:
        print(f"  ✓ {var}: Set")
        if 'URL' in var:
            print(f"    {value[:60]}...")
    else:
        print(f"  ✗ {var}: MISSING - {description}")
        all_good = False

for var, description in optional_vars.items():
    value = os.getenv(var)
    if value:
        print(f"  ✓ {var}: Set")
        if var == 'GOOGLE_CREDENTIALS_PATH':
            if os.path.exists(value):
                print(f"    File exists: {value}")
            else:
                print(f"    ⚠ File not found: {value}")
    else:
        print(f"  - {var}: Not set (optional)")

# Check Google credentials
print("\n2. Checking Google credentials...")
creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')

if creds_path and os.path.exists(creds_path):
    print(f"  ✓ Credentials file found: {creds_path}")
    creds_ok = True
elif creds_json:
    print(f"  ✓ Credentials JSON found in environment")
    creds_ok = True
else:
    print(f"  ✗ No Google credentials found!")
    print(f"    Set either GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON")
    creds_ok = False
    all_good = False

# Test Google Sheets connection
if creds_ok:
    print("\n3. Testing Google Sheets connection...")
    try:
        from data_sources import DataConnector
        
        connector = DataConnector({})
        
        # Test INDEX sheet first (simplest)
        index_url = os.getenv('INDEX_SHEET_URL')
        if index_url:
            try:
                print(f"  Testing INDEX sheet connection...")
                df = connector.read_from_sheets(index_url)
                print(f"  ✓ INDEX sheet connected!")
                print(f"    Found {len(df)} rows")
                if not df.empty:
                    print(f"    Columns: {', '.join(df.columns[:5])}")
                    if len(df.columns) > 5:
                        print(f"    ... and {len(df.columns) - 5} more")
            except Exception as e:
                print(f"  ✗ INDEX sheet connection failed: {str(e)}")
                all_good = False
        
        # Test Inventory sheet
        inventory_url = os.getenv('INVENTORY_SHEET_URL')
        if inventory_url:
            try:
                print(f"  Testing Inventory sheet connection...")
                df = connector.read_from_sheets(inventory_url)
                print(f"  ✓ Inventory sheet connected!")
                print(f"    Found {len(df)} rows")
            except Exception as e:
                print(f"  ✗ Inventory sheet connection failed: {str(e)}")
                all_good = False
        
    except ImportError as e:
        print(f"  ✗ Could not import DataConnector: {str(e)}")
        print(f"    Make sure you've installed requirements: pip install -r requirements.txt")
        all_good = False
    except Exception as e:
        print(f"  ✗ Connection test failed: {str(e)}")
        all_good = False
else:
    print("\n3. Skipping connection test (no credentials)")

# Summary
print("\n" + "=" * 60)
if all_good:
    print("✓ SETUP LOOKS GOOD!")
    print("\nYou can now run the app with:")
    print("  python app.py")
    print("\nOr test locally:")
    print("  python -m flask run")
else:
    print("✗ SETUP INCOMPLETE")
    print("\nPlease fix the issues above before running the app.")
print("=" * 60)

