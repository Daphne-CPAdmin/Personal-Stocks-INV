# Personal Inventory Management Web App

A modern web application for managing product inventory, tracking sales, calculating tithes, and creating invoices. Deployed on Railway.com with Google Sheets as the data storage backend.

## Features

- **Inventory Management**: Add products with base prices and procurement fees, track status (in stock, used, freebie, raffled, sold)
- **Sold Items Tracking**: Automatically calculate profit, tithe (10%), and profit after tithe for sold items
- **Tithe Management**: Track whether tithes have been kept with visual indicators
- **Invoice Creation**: Create invoices with multiple items and customer information
- **Customer Management**: Automatically track customer orders and spending

## Setup

### 1. Google Sheets Setup

Create a Google Sheets spreadsheet with 4 tabs:

1. **Inventory** - Columns: `product_name`, `base_price`, `procurement_fees`, `total_cost_per_unit`, `quantity`, `status`, `remarks`, `date_added`, `selling_price`, `profit`, `tithe`, `profit_after_tithe`, `date_sold`
2. **Sold Items** - Columns: `product_name`, `base_price`, `procurement_fees`, `total_cost`, `selling_price`, `profit`, `tithe`, `profit_after_tithe`, `tithe_kept`, `remarks`, `date_sold`
3. **Invoices** - Columns: `invoice_number`, `customer_name`, `items`, `total_amount`, `invoice_date`, `created_at`
4. **Customers** - Columns: `customer_name`, `total_orders`, `total_spent`, `first_order_date`, `last_order_date`

### 2. Google Service Account Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Sheets API and Google Drive API
4. Create a Service Account
5. Download the JSON credentials file
6. Share your Google Sheets with the service account email (found in credentials JSON)

### 3. Local Development

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your values
4. Run the application:
   ```bash
   python app.py
   ```
5. Open http://localhost:5000 in your browser

### 4. Railway Deployment

1. Push your code to GitHub
2. Connect your GitHub repository to Railway
3. Add environment variables in Railway dashboard:
   - `SECRET_KEY` - A random secret key for Flask sessions
   - `INVENTORY_SHEET_URL` - Full URL to your Inventory sheet tab
   - `SOLD_ITEMS_SHEET_URL` - Full URL to your Sold Items sheet tab
   - `INVOICES_SHEET_URL` - Full URL to your Invoices sheet tab
   - `CUSTOMERS_SHEET_URL` - Full URL to your Customers sheet tab
   - `GOOGLE_CREDENTIALS_JSON` - Paste entire JSON credentials as single line (no quotes)
   - `PORT` - Railway sets this automatically
4. Deploy!

## Usage

- **Add Products**: Click "Add Product" on the Inventory page
- **Update Status**: Click "Update Status" on any product to mark it as used, freebie, raffled, or sold
- **Track Tithes**: On the Sold Items page, check the "Kept" checkbox when you've set aside the tithe
- **Create Invoices**: Use the Invoices page to create invoices and automatically log customer information

## Notes

- All data is stored in Google Sheets - no database required
- The app automatically calculates profit and tithe (10% of profit) when items are marked as sold
- Tithe calculation: `profit = selling_price - (base_price + procurement_fees)`, `tithe = profit * 0.10`


