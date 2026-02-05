# Setup Instructions

## Quick Start Guide

### Step 1: Create Google Sheets Spreadsheet

1. Create a new Google Sheets spreadsheet
2. Create 4 tabs with these names:
   - **Inventory**
   - **Sold Items**
   - **Invoices**
   - **Customers**

3. Set up column headers for each tab:

**Inventory Tab:**
```
product_name | base_price | procurement_fees | total_cost_per_unit | quantity | status | remarks | date_added | selling_price | profit | tithe | profit_after_tithe | date_sold
```

**Sold Items Tab:**
```
product_name | base_price | procurement_fees | total_cost | selling_price | profit | tithe | profit_after_tithe | tithe_kept | remarks | date_sold
```

**Invoices Tab:**
```
invoice_number | customer_name | items | total_amount | invoice_date | created_at
```

**Customers Tab:**
```
customer_name | total_orders | total_spent | first_order_date | last_order_date
```

### Step 2: Set Up Google Service Account

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable APIs:
   - Google Sheets API
   - Google Drive API
4. Go to "IAM & Admin" > "Service Accounts"
5. Click "Create Service Account"
6. Give it a name (e.g., "inventory-manager")
7. Click "Create and Continue"
8. Skip role assignment, click "Continue"
9. Click "Done"
10. Click on the service account you just created
11. Go to "Keys" tab
12. Click "Add Key" > "Create new key"
13. Choose JSON format
14. Download the JSON file

### Step 3: Share Google Sheets with Service Account

1. Open your Google Sheets spreadsheet
2. Click "Share" button
3. Copy the email address from the service account JSON file (it looks like: `your-service-account@project-id.iam.gserviceaccount.com`)
4. Paste it in the share dialog
5. Give it "Editor" access
6. Click "Send"

### Step 4: Get Sheet URLs

1. Open your Google Sheets spreadsheet
2. Click on the "Inventory" tab
3. Copy the full URL from your browser (should look like: `https://docs.google.com/spreadsheets/d/ABC123.../edit#gid=0`)
4. Repeat for each tab (Sold Items, Invoices, Customers)
5. Each tab will have a different `gid=` number at the end

### Step 5: Local Development Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add:
   - `SECRET_KEY` - Any random string (e.g., `my-secret-key-123`)
   - `INVENTORY_SHEET_URL` - Full URL to Inventory tab
   - `SOLD_ITEMS_SHEET_URL` - Full URL to Sold Items tab
   - `INVOICES_SHEET_URL` - Full URL to Invoices tab
   - `CUSTOMERS_SHEET_URL` - Full URL to Customers tab
   - `GOOGLE_CREDENTIALS_PATH` - Path to your downloaded JSON file (e.g., `./credentials.json`)

3. Place your service account JSON file in the project root and name it `credentials.json` (or update the path in `.env`)

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Run the app:
   ```bash
   python app.py
   ```

6. Open http://localhost:5000 in your browser

### Step 6: Railway Deployment

1. Push your code to GitHub

2. Go to https://railway.app/ and sign in

3. Click "New Project" > "Deploy from GitHub repo"

4. Select your repository

5. Add environment variables in Railway dashboard:
   - `SECRET_KEY` - A random secret key
   - `INVENTORY_SHEET_URL` - Full URL to Inventory tab
   - `SOLD_ITEMS_SHEET_URL` - Full URL to Sold Items tab
   - `INVOICES_SHEET_URL` - Full URL to Invoices tab
   - `CUSTOMERS_SHEET_URL` - Full URL to Customers tab
   - `GOOGLE_CREDENTIALS_JSON` - Open your credentials.json file, copy ALL the content, and paste it as a single line (remove all line breaks, but keep it as valid JSON)

6. Railway will automatically detect Python and deploy

7. Your app will be live at `https://your-app-name.railway.app`

## Troubleshooting

**"Google Sheets client not initialized" error:**
- Make sure your service account JSON file is correct
- Make sure you shared the spreadsheet with the service account email
- Check that `GOOGLE_CREDENTIALS_PATH` or `GOOGLE_CREDENTIALS_JSON` is set correctly

**"Could not extract spreadsheet ID from URL" error:**
- Make sure you're using the full URL from your browser
- The URL should include `#gid=` at the end
- Copy the URL while viewing the specific tab you want

**Empty data showing:**
- Make sure your Google Sheets have the correct column headers
- The app will create columns automatically, but headers help

**Port errors on Railway:**
- Railway sets `PORT` automatically - don't override it
- The app reads `PORT` from environment variables


