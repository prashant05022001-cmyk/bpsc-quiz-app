import streamlit as st
import json
import os
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CLOUD DATABASE CONNECTION LOGIC ---
def get_gspread_client():
    try:
        # Load secrets from Streamlit
        json_creds = json.loads(st.secrets["GSPREAD_JSON"])
        creds = Credentials.from_service_account_info(json_creds)
        return gspread.authorize(creds)
    except:
        return None

def save_data_to_cloud(data):
    try:
        client = get_gspread_client()
        if client:
            sheet = client.open_by_key(st.secrets["SHEET_ID"]).sheet1
            # Save the entire state as a JSON string in Cell A1
            sheet.update(range_name='A1', values=[[json.dumps(data)]])
    except Exception as e:
        st.error(f"Sync Error: {e}")

def load_data_from_cloud():
    try:
        client = get_gspread_client()
        if client:
            sheet = client.open_by_key(st.secrets["SHEET_ID"]).sheet1
            val = sheet.acell('A1').value
            return json.loads(val) if val else None
    except:
        return None

# --- 2. INITIALIZE APP STATE ---
if 'vault' not in st.session_state:
    # Try Cloud first, then local file
    cloud_data = load_data_from_cloud()
    if cloud_data:
        st.session_state.update(cloud_data)
        st.success("☁️ Cloud Database Active: Data synced from Google Sheets.")
    elif os.path.exists("database.json"):
        with open("database.json", "r") as f:
            st.session_state.update(json.load(f))
    else:
        st.session_state['vault'] = {}
        st.session_state['old_questions'] = []
        st.session_state['quiz_history_log'] = []

# --- 3. SAVE FUNCTION (Use this everywhere!) ---
def save_data():
    # Save locally
    with open("database.json", "w") as f:
        json.dump(st.session_state, f)
    # Save to Google Sheets
    save_data_to_cloud(st.session_state)

# --- 4. YOUR INTERFACE ---
st.title("📚 Civil Services Smart Quiz Dashboard")
# ... [Paste your existing Dashboard/Tab/UI code here] ...
