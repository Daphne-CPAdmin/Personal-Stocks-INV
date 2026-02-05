import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
from urllib.parse import urlparse, parse_qs
import logging

logger = logging.getLogger(__name__)

class DataConnector:
    """Handles Google Sheets read/write operations"""
    
    def __init__(self, config={}):
        self.config = config
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Google Sheets client"""
        try:
            # Check for service account credentials
            creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
            if creds_path and os.path.exists(creds_path):
                scope = ['https://spreadsheets.google.com/feeds',
                        'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(creds_path, scopes=scope)
                self.client = gspread.authorize(creds)
            else:
                # Try environment variable with JSON credentials
                creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if creds_json:
                    import json
                    creds_dict = json.loads(creds_json)
                    scope = ['https://spreadsheets.google.com/feeds',
                            'https://www.googleapis.com/auth/drive']
                    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                    self.client = gspread.authorize(creds)
                else:
                    logger.warning("No Google credentials found. Google Sheets features will not work.")
        except Exception as e:
            logger.error(f"Error initializing Google Sheets client: {str(e)}")
            self.client = None
    
    def _extract_sheet_info(self, url):
        """Extract spreadsheet ID and gid from Google Sheets URL"""
        try:
            parsed = urlparse(url)
            # Extract spreadsheet ID from URL
            path_parts = parsed.path.split('/')
            spreadsheet_id = None
            for i, part in enumerate(path_parts):
                if part == 'd' and i + 1 < len(path_parts):
                    spreadsheet_id = path_parts[i + 1]
                    break
            
            # Extract gid from fragment or query
            gid = '0'  # Default to first sheet
            if parsed.fragment:
                fragment_params = parse_qs(parsed.fragment)
                if 'gid' in fragment_params:
                    gid = fragment_params['gid'][0]
            elif 'gid' in parse_qs(parsed.query):
                gid = parse_qs(parsed.query)['gid'][0]
            
            return spreadsheet_id, gid
        except Exception as e:
            logger.error(f"Error extracting sheet info from URL: {str(e)}")
            return None, None
    
    def read_from_sheets(self, url):
        """Read data from Google Sheets"""
        if not self.client:
            raise ValueError("Google Sheets client not initialized. Check credentials.")
        
        try:
            spreadsheet_id, gid = self._extract_sheet_info(url)
            if not spreadsheet_id:
                raise ValueError("Could not extract spreadsheet ID from URL")
            
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.get_worksheet_by_id(int(gid))
            
            # Get all values
            data = worksheet.get_all_records()
            
            if not data:
                # Return empty DataFrame
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            # Replace empty strings with None for consistency
            df = df.replace('', None)
            logger.info(f"Read {len(df)} rows from Google Sheets")
            return df
        except Exception as e:
            logger.error(f"Error reading from Google Sheets: {str(e)}")
            raise
    
    def write_to_sheets(self, df, url):
        """Write DataFrame to Google Sheets"""
        if not self.client:
            raise ValueError("Google Sheets client not initialized. Check credentials.")
        
        try:
            spreadsheet_id, gid = self._extract_sheet_info(url)
            if not spreadsheet_id:
                raise ValueError("Could not extract spreadsheet ID from URL")
            
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.get_worksheet_by_id(int(gid))
            
            # Clear existing content
            worksheet.clear()
            
            # Write headers
            headers = list(df.columns)
            worksheet.append_row(headers)
            
            # Write data
            for _, row in df.iterrows():
                values = [str(val) if pd.notna(val) else '' for val in row.values]
                worksheet.append_row(values)
            
            logger.info(f"Wrote {len(df)} rows to Google Sheets")
        except Exception as e:
            logger.error(f"Error writing to Google Sheets: {str(e)}")
            raise

