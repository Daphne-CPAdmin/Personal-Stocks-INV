# Setup Verification Checklist

## ✅ What I've Updated

1. **Added INDEX Sheet Support**
   - App now reads product names from your INDEX sheet
   - Product name autocomplete dropdown in "Add Product" form
   - Uses INDEX_SHEET_URL from your .env file

2. **Product Name Autocomplete**
   - When adding a product, you'll see suggestions from your INDEX sheet
   - Type to filter, or select from the dropdown

## 🔍 Manual Setup Verification

Since I can't directly access your `.env` file (it's protected), please verify:

### 1. Environment Variables Check

Make sure your `.env` file has all these variables set:

```bash
# Required
SECRET_KEY=your-secret-key-here
INVENTORY_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit#gid=0
SOLD_ITEMS_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit#gid=...
INVOICES_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit#gid=...
CUSTOMERS_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit#gid=...
INDEX_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit#gid=...

# One of these (for local development)
GOOGLE_CREDENTIALS_PATH=credentials.json

# OR (for Railway deployment)
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
```

### 2. INDEX Sheet Structure

Your INDEX sheet should have product names in one of these formats:

**Option A: Column named "product_name"**
```
product_name
Product A
Product B
Product C
```

**Option B: First column (any header)**
```
Products
Product A
Product B
Product C
```

### 3. Test the Setup

**Option 1: Run the test script (after installing dependencies)**
```bash
pip install -r requirements.txt
python test_setup.py
```

**Option 2: Run the app directly**
```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 and:
- Go to Inventory page
- Click "Add Product"
- Type in the product name field - you should see autocomplete suggestions from your INDEX sheet

### 4. Common Issues

**"Google Sheets client not initialized"**
- Check that `GOOGLE_CREDENTIALS_PATH` points to a valid JSON file
- OR check that `GOOGLE_CREDENTIALS_JSON` is set correctly
- Make sure you shared your spreadsheet with the service account email

**"Could not extract spreadsheet ID from URL"**
- Make sure URLs include `#gid=` at the end
- Copy the full URL from your browser when viewing each tab

**"No product names showing in autocomplete"**
- Check INDEX_SHEET_URL is set correctly
- Verify INDEX sheet has data in first column or "product_name" column
- Check logs/audit_log.txt for errors

**"ModuleNotFoundError"**
- Run: `pip install -r requirements.txt`
- Make sure you're in a virtual environment (recommended)

## 🚀 Next Steps

1. **Install dependencies** (if not done):
   ```bash
   pip install -r requirements.txt
   ```

2. **Test locally**:
   ```bash
   python app.py
   ```

3. **Verify INDEX sheet integration**:
   - Add a product and check if autocomplete works
   - Product names from INDEX sheet should appear as you type

4. **Deploy to Railway** (when ready):
   - Push to GitHub
   - Connect to Railway
   - Add all environment variables (including INDEX_SHEET_URL)
   - Use GOOGLE_CREDENTIALS_JSON (not PATH) for Railway

## 📝 Notes

- The INDEX sheet is optional but recommended for consistent product naming
- Product names are loaded when the Inventory page loads
- If INDEX sheet is empty or not accessible, the app will still work (just no autocomplete)

