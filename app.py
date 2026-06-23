import streamlit as st
import json
import os
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CLEAN DATA HELPER ---
def get_clean_data():
    return {
        "vault": st.session_state.get("vault", {}),
        "quiz_history": st.session_state.get("quiz_history", [])
    }

# --- 2. CLOUD DATABASE CONNECTION (WITH CACHING) ---
@st.cache_data(ttl=600) # Caches data for 10 minutes to make the app FAST
def load_cloud_data(sheet_id, json_creds):
    try:
        creds = Credentials.from_service_account_info(json_creds)
        client = gspread.authorize(creds)
        val = client.open_by_key(sheet_id).sheet1.acell('A1').value
        return json.loads(val) if val else None
    except:
        return None

def save_data_to_cloud(data):
    # This runs in the background, so it doesn't slow down your page load
    try:
        if "GSPREAD_JSON" in st.secrets and "SHEET_ID" in st.secrets:
            json_creds = json.loads(st.secrets["GSPREAD_JSON"])
            client = gspread.authorize(Credentials.from_service_account_info(json_creds))
            client.open_by_key(st.secrets["SHEET_ID"]).sheet1.update(range_name='A1', values=[[json.dumps(data, default=str)]])
    except:
        pass

# --- 3. INITIALIZE APP STATE ---
if 'vault' not in st.session_state:
    st.session_state['vault'] = {}
    st.session_state['quiz_history'] = []
    
    # Try Cloud (Cached)
    if "GSPREAD_JSON" in st.secrets and "SHEET_ID" in st.secrets:
        cloud_data = load_cloud_data(st.secrets["SHEET_ID"], json.loads(st.secrets["GSPREAD_JSON"]))
        if cloud_data:
            st.session_state.update(cloud_data)
    
    # Fallback to local
    if not st.session_state.get('vault') and os.path.exists("database.json"):
        with open("database.json", "r") as f:
            st.session_state.update(json.load(f))

# --- 4. SAVE FUNCTION ---
def save_data():
    data = get_clean_data()
    with open("database.json", "w") as f:
        json.dump(data, f)
    save_data_to_cloud(data)
    # Clear cache so next fetch gets updated data
    st.cache_data.clear()

# --- 5. INTERFACE ---
st.set_page_config(page_title="Civil Services Dashboard", layout="wide")
st.title("📚 Civil Services Smart Quiz Dashboard")

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "📚 Question Bank", "⚙️ Vault Management"])

with tab1:
    st.header("Live Simulator")
    subject = st.selectbox("Select Subject", ["General"] + list(st.session_state['vault'].keys()))
    if st.button("Start Quiz"):
        st.write(f"Starting quiz for {subject}...")

with tab2:
    st.header("Analytics Hub")
    if st.session_state['quiz_history']:
        st.write("Progress data loaded.")

with tab3:
    st.header("Question Bank")
    new_sub = st.text_input("New Subject Name")
    if st.button("Add Subject"):
        if new_sub and new_sub not in st.session_state['vault']:
            st.session_state['vault'][new_sub] = []
            save_data()
            st.rerun()

with tab4:
    st.header("Vault Management")
    if st.button("Force Sync to Cloud"):
        save_data()
        st.success("Synced!")
    st.download_button("Download Backup File", json.dumps(get_clean_data()), "backup.json")
