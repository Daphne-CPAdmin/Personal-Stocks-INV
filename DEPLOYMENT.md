# Deployment Guide - GitHub & Railway

This guide will help you deploy your Inventory Management app to GitHub and Railway.

## Prerequisites

- GitHub account
- Railway account (sign up at https://railway.app)
- Google Service Account credentials JSON file

## Step 1: Initialize Git Repository

```bash
# Initialize git repository
git init

# Add all files
git add .

# Make initial commit
git commit -m "Initial commit: Inventory Management App"
```

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Create a new repository (e.g., `personal-stocks-inventory`)
3. **DO NOT** initialize with README, .gitignore, or license
4. Copy the repository URL

## Step 3: Push to GitHub

```bash
# Add GitHub remote (replace with your repository URL)
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Step 4: Deploy to Railway

### 4.1 Create New Project on Railway

1. Go to https://railway.app
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub account
5. Select your repository (`personal-stocks-inventory`)

### 4.2 Configure Environment Variables

In Railway dashboard, go to your project → **Variables** tab and add:

**Required Variables:**
```
SECRET_KEY=your-secret-key-here-change-in-production
INVENTORY_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=0
SOLD_ITEMS_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=123456
INVOICES_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=234567
CUSTOMERS_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=345678
USED_FREEBIE_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=567890
INDEX_SHEET_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=456789
```

**Google Credentials (Choose ONE option):**

**Option 1: JSON File Path (if you upload credentials.json)**
```
GOOGLE_CREDENTIALS_PATH=/app/credentials.json
```

**Option 2: JSON as Environment Variable (Recommended)**
```
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"...","private_key_id":"...","private_key":"...","client_email":"...","client_id":"...","auth_uri":"...","token_uri":"...","auth_provider_x509_cert_url":"...","client_x509_cert_url":"..."}
```

**Important:** 
- Copy the ENTIRE JSON content from your `credentials.json` file
- Paste it as a single line (no line breaks)
- Remove all quotes around the JSON value in Railway

### 4.3 Configure Build Settings

Railway will automatically detect Python and use `requirements.txt`. The `Procfile` and `railway.json` are already configured.

### 4.4 Deploy

1. Railway will automatically start building when you push to GitHub
2. Check the **Deployments** tab to see build progress
3. Once deployed, Railway will provide a public URL (e.g., `https://your-app.railway.app`)

## Step 5: Update Google Sheets Permissions

Make sure your Google Service Account email has **Editor** access to your Google Sheets:

1. Open your Google Sheet
2. Click **Share** button
3. Add your service account email (found in `credentials.json` → `client_email`)
4. Give it **Editor** permissions
5. Click **Send**

## Step 6: Test Your Deployment

1. Visit your Railway URL
2. Test adding a product
3. Check that it appears in your Google Sheet
4. Test updating status, creating invoices, etc.

## Troubleshooting

### Build Fails

- Check Railway logs in the **Deployments** tab
- Verify `requirements.txt` has all dependencies
- Check Python version compatibility

### App Crashes on Startup

- Check environment variables are set correctly
- Verify Google credentials format
- Check Railway logs for error messages

### Google Sheets Not Updating

- Verify service account has Editor access to sheets
- Check sheet URLs are correct in environment variables
- Verify `GOOGLE_CREDENTIALS_JSON` or `GOOGLE_CREDENTIALS_PATH` is set

### Port Issues

- Railway automatically sets `PORT` environment variable
- The app uses `os.getenv('PORT', 5000)` to handle this

## Updating Your App

After making changes:

```bash
# Make your changes
git add .
git commit -m "Description of changes"
git push origin main
```

Railway will automatically redeploy when you push to GitHub!

## Security Notes

- ✅ `.env` is in `.gitignore` - never commit secrets
- ✅ `credentials.json` is in `.gitignore` - never commit credentials
- ✅ Use Railway environment variables for production secrets
- ✅ Change `SECRET_KEY` to a strong random value in production

