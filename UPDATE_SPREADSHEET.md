# Update Spreadsheet Structure

## Quick Guide

I've created a script to automatically update your Google Sheets with the correct column structure.

## Step 1: Make sure credentials are set up

Your `.env` file should have either:
- `GOOGLE_CREDENTIALS_PATH=credentials.json` (path to your service account JSON file)
- OR `GOOGLE_CREDENTIALS_JSON={...}` (the JSON content as environment variable)

## Step 2: Run the update script

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Run the update script
python components/update_spreadsheet_structure.py
```

The script will:
- ✅ Read your current spreadsheet structure
- ✅ Map old column names to new ones (base_price → total_price, etc.)
- ✅ Preserve all existing data
- ✅ Update column headers to match the new structure
- ✅ Create headers for tabs that don't exist yet

## What Gets Updated

**Inventory Tab:**
- Old: `base_price`, `procurement_fees`
- New: `total_price`, `shipping_admin_fee`
- Added: All new columns in correct order

**Sold Items Tab:**
- Updated to include: `total_price`, `shipping_admin_fee`, `total_cost_per_unit`, `quantity`
- All columns match new structure

**Invoices Tab:**
- Keeps existing structure (already correct)

**Customers Tab:**
- Adds `products_purchased` column for tracking product-level details

**INDEX Tab:**
- Ensures `product_name` column exists in Column A

## Manual Alternative

If you prefer to update manually, see `SPREADSHEET_STRUCTURE.md` for the exact column headers needed for each tab.

## After Running

Once updated, your spreadsheet will be ready to use with the web app. All existing data will be preserved and mapped to the new column names.

