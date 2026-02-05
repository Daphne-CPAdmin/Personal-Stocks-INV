# Quick Deployment Checklist

## ✅ Completed
- [x] Git repository initialized
- [x] Initial commit created
- [x] .gitignore configured (protects .env, credentials.json, logs, venv)
- [x] Procfile ready for Railway
- [x] railway.json configured
- [x] App configured for Railway PORT

## Next Steps

### 1. ✅ GitHub Repository Created

**Repository:** `https://github.com/Daphne-CPAdmin/Personal-Stocks-INV`

### 2. Push to GitHub

Run these commands to push your code:

```bash
git branch -M main
git push -u origin main
```

**Note:** The remote is already configured. If you need to verify:
```bash
git remote -v
```

You should see:
```
origin	https://github.com/Daphne-CPAdmin/Personal-Stocks-INV (fetch)
origin	https://github.com/Daphne-CPAdmin/Personal-Stocks-INV (push)
```

### 3. Deploy to Railway

1. **Sign up/Login:** Go to https://railway.app
2. **New Project:** Click "New Project" → "Deploy from GitHub repo"
3. **Authorize:** Allow Railway to access your GitHub account
4. **Select Repo:** Choose `Daphne-CPAdmin/Personal-Stocks-INV`
5. **Add Variables:** Go to your project → **Variables** tab

Add these environment variables:

```
SECRET_KEY=your-random-secret-key-here
INVENTORY_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=0
SOLD_ITEMS_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=123456
INVOICES_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=234567
CUSTOMERS_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=345678
USED_FREEBIE_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=567890
INDEX_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_ID/edit#gid=456789
```

**For Google Credentials (choose ONE):**

**Option A - JSON as Environment Variable (Recommended):**
```
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}
```
*(Copy entire JSON from credentials.json, paste as single line, no quotes around the value)*

**Option B - Upload File:**
If you upload `credentials.json` to Railway:
```
GOOGLE_CREDENTIALS_PATH=/app/credentials.json
```

6. **Deploy:** Railway will automatically build and deploy
7. **Get URL:** Once deployed, Railway provides a public URL

### 4. Share Google Sheets

1. Open your Google Sheet
2. Click **Share** button
3. Add your service account email (from `credentials.json` → `client_email`)
4. Give it **Editor** permissions
5. Click **Send**

### 5. Test

Visit your Railway URL and test:
- Adding a product
- Updating product status
- Creating an invoice
- Check that data appears in Google Sheets

## Troubleshooting

**Build fails?**
- Check Railway logs
- Verify all environment variables are set
- Check `requirements.txt` is correct

**App crashes?**
- Check Railway logs for errors
- Verify Google credentials format
- Ensure service account has access to sheets

**Sheets not updating?**
- Verify service account email has Editor access
- Check sheet URLs are correct
- Verify `GOOGLE_CREDENTIALS_JSON` is set correctly

## Updating After Changes

```bash
git add .
git commit -m "Description of changes"
git push origin main
```

Railway will automatically redeploy!

