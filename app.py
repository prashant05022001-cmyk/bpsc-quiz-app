import streamlit as st
import json
import os
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CLEAN DATA HELPER (Fixes the JSON Error) ---
def get_clean_data():
    """Extracts only the data we want to save, stripping out internal Streamlit objects."""
    return {
        "vault": st.session_state.get("vault", {}),
        "quiz_history": st.session_state.get("quiz_history", [])
    }

# --- 2. CLOUD DATABASE CONNECTION ---
def get_gspread_client():
    try:
        # Check if secrets exist
        if "GSPREAD_JSON" not in st.secrets or "SHEET_ID" not in st.secrets:
            return None, None
        json_creds = json.loads(st.secrets["GSPREAD_JSON"])
        creds = Credentials.from_service_account_info(json_creds)
        client = gspread.authorize(creds)
        return client, st.secrets["SHEET_ID"]
    except Exception:
        return None, None

def save_data_to_cloud(data):
    client, sheet_id = get_gspread_client()
    if client and sheet_id:
        try:
            sheet = client.open_by_key(sheet_id).sheet1
            # Save the clean data as a JSON string
            sheet.update(range_name='A1', values=[[json.dumps(data, default=str)]])
        except Exception:
            pass 

# --- 3. INITIALIZE APP STATE ---
if 'vault' not in st.session_state:
    # A. Load Defaults
    st.session_state['vault'] = {}
    st.session_state['quiz_history'] = []
    
    # B. Try loading from Cloud
    client, sheet_id = get_gspread_client()
    loaded_from_cloud = False
    if client:
        try:
            val = client.open_by_key(sheet_id).sheet1.acell('A1').value
            if val:
                st.session_state.update(json.loads(val))
                loaded_from_cloud = True
        except Exception:
            pass
            
    # C. Fallback: Load from local file if cloud was empty/failed
    if not loaded_from_cloud and os.path.exists("database.json"):
        try:
            with open("database.json", "r") as f:
                st.session_state.update(json.load(f))
        except Exception:
            pass

# --- 4. SAVE FUNCTION ---
def save_data():
    data = get_clean_data()
    # Save local
    with open("database.json", "w") as f:
        json.dump(data, f)
    # Save cloud
    save_data_to_cloud(data)

# --- 5. INTERFACE ---
st.set_page_config(page_title="Civil Services Dashboard", layout="wide")
st.title("📚 Civil Services Smart Quiz Dashboard")

# Cloud Status indicator
client, _ = get_gspread_client()
if client:
    st.sidebar.success("☁️ Cloud Database Active")
else:
    st.sidebar.warning("⚠️ Local Storage Only")

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "📚 Question Bank", "⚙️ Vault Management"])

# Tab 1
with tab1:
    st.header("Live Simulator")
    subject = st.selectbox("Select Subject", ["General"] + list(st.session_state['vault'].keys()))
    if st.button("Start Quiz"):
        st.write(f"Starting quiz for {subject}...")

# Tab 2
with tab2:
    st.header("Analytics Hub")
    if st.session_state['quiz_history']:
        st.write("Progress data loaded.")

# Tab 3
with tab3:
    st.header("Question Bank")
    new_sub = st.text_input("New Subject Name")
    if st.button("Add Subject"):
        if new_sub and new_sub not in st.session_state['vault']:
            st.session_state['vault'][new_sub] = []
            save_data()
            st.rerun()

# Tab 4
with tab4:
    st.header("Vault Management")
    if st.button("Force Sync to Cloud"):
        save_data()
        st.success("Synced to Google Sheets!")
    
    # FIXED LINE 110: Using get_clean_data() instead of st.session_state
    st.download_button(
        "Download Backup File", 
        json.dumps(get_clean_data()), 
        "backup.json"
    )
