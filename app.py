import streamlit as st
import json
import os
import gspread
from google.oauth2.service_account import Credentials

# --- 1. CLOUD DATABASE CONNECTION ---
def get_gspread_client():
    try:
        # Check if secrets exist
        if "GSPREAD_JSON" not in st.secrets or "SHEET_ID" not in st.secrets:
            return None, None
        json_creds = json.loads(st.secrets["GSPREAD_JSON"])
        creds = Credentials.from_service_account_info(json_creds)
        client = gspread.authorize(creds)
        return client, st.secrets["SHEET_ID"]
    except:
        return None, None

def save_data_to_cloud(data):
    client, sheet_id = get_gspread_client()
    if client and sheet_id:
        try:
            sheet = client.open_by_key(sheet_id).sheet1
            sheet.update(range_name='A1', values=[[json.dumps(data, default=str)]])
        except:
            pass 

# --- 2. INITIALIZE APP STATE ---
if 'vault' not in st.session_state:
    # A. Try loading from Cloud
    client, sheet_id = get_gspread_client()
    loaded_from_cloud = False
    if client:
        try:
            val = client.open_by_key(sheet_id).sheet1.acell('A1').value
            if val:
                st.session_state.update(json.loads(val))
                loaded_from_cloud = True
        except:
            pass
            
    # B. If Cloud failed, load from local file
    if not loaded_from_cloud and os.path.exists("database.json"):
        with open("database.json", "r") as f:
            st.session_state.update(json.load(f))
            
    # C. Default setup
    if 'vault' not in st.session_state:
        st.session_state['vault'] = {}
        st.session_state['quiz_history'] = []

# --- 3. SAVE FUNCTION ---
def save_data():
    with open("database.json", "w") as f:
        json.dump(st.session_state, f, default=str)
    save_data_to_cloud(st.session_state)

# --- 4. INTERFACE ---
st.set_page_config(page_title="Civil Services Dashboard", layout="wide")
st.title("📚 Civil Services Smart Quiz Dashboard")

# Cloud Status indicator
client, _ = get_gspread_client()
if client:
    st.sidebar.success("☁️ Cloud Database Active")
else:
    st.sidebar.warning("⚠️ Local Storage Only")

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "📚 Question Bank", "⚙️ Vault Management"])

# TAB 1: Live Simulator
with tab1:
    st.header("Live Simulator")
    subject = st.selectbox("Select Subject", ["General"] + list(st.session_state['vault'].keys()))
    if st.button("Start Quiz"):
        st.write(f"Starting quiz for {subject}...")

# TAB 2: Analytics Hub
with tab2:
    st.header("Analytics Hub")
    st.write("Progress tracking metrics will appear here.")
    if st.session_state['quiz_history']:
        st.bar_chart(st.session_state['quiz_history'])

# TAB 3: Question Bank
with tab3:
    st.header("Question Bank")
    new_sub = st.text_input("New Subject Name")
    if st.button("Add Subject"):
        st.session_state['vault'][new_sub] = []
        save_data()
        st.rerun()
    
    selected_sub = st.selectbox("Add Question to Subject:", list(st.session_state['vault'].keys()))
    q = st.text_input("Question")
    a = st.text_input("Answer")
    if st.button("Add Question"):
        st.session_state['vault'][selected_sub].append({"q": q, "a": a})
        save_data()
        st.success("Question Added!")

# TAB 4: Vault Management
with tab4:
    st.header("Vault Management")
    if st.button("Force Sync to Cloud"):
        save_data()
        st.success("Synced to Google Sheets!")
    
    st.download_button("Download Backup File", json.dumps(st.session_state), "backup.json")
