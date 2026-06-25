import streamlit as st
import streamlit.components.v1 as components
import PyPDF2
import google.generativeai as genai
import json
import random
import time
import io
import datetime
import pandas as pd
import plotly.express as px
import os
import gspread
from google.oauth2.service_account import Credentials
import dropbox
import re  # <--- NEW: Added for bulletproof chapter extraction

# --- PAGE SETUP ---
st.set_page_config(page_title="Civil Services Smart Quiz Dashboard", page_icon="📚", layout="wide")

# --- 1. CLEAN DATA HELPER ---
def get_clean_data():
    return {
        "vault": st.session_state.get('vault', {}),
        "old_questions": st.session_state.get('old_questions', []),
        "quiz_history_log": st.session_state.get('quiz_history_log', []),
        "recycle_bin": st.session_state.get('recycle_bin', {"subjects": {}, "chapters": {}, "files": {}})
    }

# --- 2. CLOUD DATABASE CONNECTION LOGIC ---
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    try:
        if "GSPREAD_JSON" not in st.secrets or "SHEET_ID" not in st.secrets:
            return None, None
            
        json_creds = json.loads(st.secrets["GSPREAD_JSON"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(json_creds).with_scopes(scopes)
        client = gspread.authorize(creds)
        return client, st.secrets["SHEET_ID"]
    except Exception:
        return None, None

def save_data_to_cloud(data):
    client, sheet_id = get_gspread_client()
    if client and sheet_id:
        try:
            sheet = client.open_by_key(sheet_id).sheet1
            json_str = json.dumps(data, default=str)
            
            chunk_size = 45000
            chunks = [[json_str[i:i+chunk_size]] for i in range(0, len(json_str), chunk_size)]
            
            sheet.clear()
            sheet.update(range_name=f'A1:A{len(chunks)}', values=chunks)
            st.cache_data.clear()
        except Exception as e:
            st.error(f"☁️ Cloud Save Error: {e}")

# --- FREE DROPBOX CLOUD STORAGE ---
def upload_pdf_to_dropbox(file_bytes, file_name):
    try:
        if "DROPBOX_TOKEN" not in st.secrets:
            return None
        dbx = dropbox.Dropbox(st.secrets["DROPBOX_TOKEN"])
        path = f"/{file_name}"
        
        dbx.files_upload(file_bytes, path, mode=dropbox.files.WriteMode.overwrite)
        
        try:
            link_info = dbx.sharing_create_shared_link_with_settings(path)
            raw_url = link_info.url
        except dropbox.exceptions.ApiError:
            links = dbx.sharing_list_shared_links(path, direct_only=True).links
            raw_url = links[0].url if links else None
            
        if raw_url:
            return raw_url.replace("?dl=0", "?dl=1")
        return None
    except Exception as e:
        st.error(f"📦 Dropbox Sync Error: {e}")
        return None

# --- 3. OPTIMIZED CACHED STORAGE LOGIC ---
DB_FILE = "database.json"

@st.cache_data(show_spinner="⚡ Syncing with Cloud Registry...")
def fetch_cloud_data():
    client, sheet_id = get_gspread_client()
    if client:
        try:
            records = client.open_by_key(sheet_id).sheet1.col_values(1)
            if records:
                val = "".join(records)
                return json.loads(val)
        except Exception:
            pass
    return None

def load_data():
    cloud_data = fetch_cloud_data()
    if cloud_data:
        return cloud_data
            
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                if "recycle_bin" not in data:
                    data["recycle_bin"] = {"subjects": {}, "chapters": {}, "files": {}}
                return data
        except Exception: pass
        
    return {
        "vault": {}, 
        "old_questions": [], 
        "quiz_history_log": [],
        "recycle_bin": {"subjects": {}, "chapters": {}, "files": {}}
    }

def save_data():
    data_to_save = get_clean_data()
    with open(DB_FILE, "w") as f:
        json.dump(data_to_save, f)
    save_data_to_cloud(data_to_save)

def get_ist_time():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)

# --- 4. INITIALIZE APP STATE ---
if 'db_loaded' not in st.session_state:
    saved_data = load_data()
    st.session_state['vault'] = saved_data.get('vault', {})
    st.session_state['old_questions'] = saved_data.get('old_questions', [])
    st.session_state['quiz_history_log'] = saved_data.get('quiz_history_log', [])
    st.session_state['recycle_bin'] = saved_data.get('recycle_bin', {"subjects": {}, "chapters": {}, "files": {}})
    st.session_state['db_loaded'] = True

if 'active_quiz' not in st.session_state: st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state: st.session_state['quiz_submitted'] = False
if 'test_config' not in st.session_state: st.session_state['test_config'] = {"marks": 2.0, "penalty": 0.66}

# --- 5. API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- 6. HELPERS ---
@st.cache_data(show_spinner=False)
def extract_index_text(file_bytes, num_pages=50):
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page_num in range(min(len(pdf_reader.pages), num_pages)):
            page_text = pdf_reader.pages[page_num].extract_text()
            if page_text: text += page_text + "\n"
        return text.strip()
    except Exception: return ""

def get_chapters_from_ai(text, subject_name, retries=3):
    prompt = f"Extract chapter names from this {subject_name} index. Return ONLY a pure JSON array of strings (e.g. [\"Chapter 1\", \"Chapter 2\"]). Absolutely no conversational text."
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    
    for attempt in range(retries):
        try:
            response = model.generate_content(
                prompt + f"\nText: {text[:30000]}", 
                generation_config={"response_mime_type": "application/json"},
                safety_settings=safety_settings
            )
            raw_text = response.text.strip()
            
            # --- NEW: Bulletproof Regex Scanner ---
            # This hunts down the brackets [ ] and rips the array out, ignoring AI garbage text.
            match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            # Fallback for old parsing method
            if raw_text.startswith("```json"): 
                raw_text = raw_text[7:-3].strip()
            elif raw_text.startswith("```"): 
                raw_text = raw_text[3:-3].strip()
                
            return json.loads(raw_text)
            
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e): 
                st.toast("⚠️ Google API is rate-limiting you. Pausing for 15 seconds to try again...", icon="⏳")
                time.sleep(15)
            else:
                pass 
    return []

def generate_new_questions(subject, chapters, difficulty, count, item_types, vault_full_text, retries=2):
    if count <= 0: return []
    relevant_context = ""
    if vault_full_text:
        relevant_context = vault_full_text[:2000] 
        for ch in chapters:
            start_idx = vault_full_text.find(ch)
            if start_idx != -1:
                relevant_context += "\n... " + vault_full_text[max(0, start_idx-500) : start_idx+1500]
    relevant_context = relevant_context[:10000]

    prompt = f"""
    Elite Civil Services Examiner Mode. Generate {count} distinct questions for Subject: {subject} | Chapters: {', '.join(chapters)}.
    Difficulty: {difficulty}. Formats: {', '.join(item_types)}. Source Material context: {relevant_context}

    CRITICAL INSTRUCTION FOR 'explanation': Do NOT just explain the correct option. You MUST provide a COMPREHENSIVE, multi-paragraph revision summary of the ENTIRE core topic mentioned in the question based strictly on the provided context. For example, if the question is about Gandhi, provide a full summary of his activities, movements, and timeline; if about the Portuguese, cover their arrival, governors, policies, and decline. 

    Return JSON array exactly:
    [ {{"id": {random.randint(10000,99999)}, "type": "MCQ", "chapter": "{chapters[0] if chapters else 'General'}", "question": "Q?", "options": {{"A": "1", "B": "2", "C": "3", "D": "4"}}, "correct": "A", "explanation": "Massive detailed topic summary here...", "extra_info": "Fact."}} ]
    """
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    for attempt in range(retries):
        try:
            response = model.generate_content(
                prompt, 
                generation_config={"response_mime_type": "application/json"},
                safety_settings=safety_settings
            )
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                st.warning("Speed limit hit. AI is pausing. Retrying in 20s...")
                time.sleep(20)
            else: 
                st.error(f"🤖 AI Question Generation Error: {e}")
                return []
    return []

def build_markdown_export(quiz_pool, subject):
    md = f"# Practice Set: {subject}\n\n"
    for idx, q in enumerate(quiz_pool):
        md += f"### Q{idx+1} [{q.get('type', 'MCQ')}] ({q.get('chapter', '')})\n{q['question']}\n\n"
        for k, v in q['options'].items(): md += f"- **{k}**: {v}\n"
        md += f"\n**Correct:** {q['correct']} | **Comprehensive Review:** {q['explanation']}\n\n---\n"
    return md

def get_active_chapters(subject):
    sub_data = st.session_state['vault'].get(subject, {})
    active_chaps = list(sub_data.get("manual_chapters", []))
    
    file_mapping = sub_data.get("file_chapter_mapping", {})
    active_files = sub_data.get("files", [])
    
    for f_name in active_files:
        if f_name in file_mapping:
            active_chaps.extend(file_mapping[f_name])
            
    return sorted(list(set(active_chaps)))

# --- 7. APP LAYOUT ---
st.title("📚 Civil Services Smart Quiz Dashboard")

client, _ = get_gspread_client()
if client:
    st.sidebar.success("☁️ Cloud Database Active")
else:
    st.sidebar.warning("⚠️ Local Storage Only")

st.write("---")

tab_quiz, tab_analytics, tab_history, tab_settings = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "🗄️ Question Bank", "⚙️ Vault Management"])

with tab_quiz:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.header("1. Sync Content Vault")
        existing_subs = list(st.session_state['vault'].keys())
        
        sub_options = []
        if existing_subs:
            sub_options = ["All Subjects"] + [f"{s} ({len(get_active_chapters(s))} Chapters)" for s in existing_subs]
            
        sub_mode = st.radio("Mode:", ["Existing Subject", "New Subject"])
        
        if sub_mode == "Existing Subject" and sub_options:
            selected_sub_display = st.selectbox("Subject:", options=sub_options)
            sub_input = selected_sub_display.split(" (")[0] if " (" in selected_sub_display else selected_sub_display
        else:
            sub_input = st.text_input("Enter New Subject Name:")
        
        if sub_input and sub_input != "All Subjects" and sub_input not in st.session_state['vault']:
            st.session_state['vault'][sub_input] = {
                "chapters": [], 
                "content": "", 
                "files": [],
                "file_chapter_mapping": {},
                "manual_chapters": [],
                "file_links": {}
            }
            save_data()
            st.rerun()

        st.write("---")
        if sub_input != "All Subjects" and sub_input:
            prev_files = st.session_state['vault'].get(sub_input, {}).get("files", [])
            if prev_files:
                st.info(f"📁 **Active PDFs stored for {sub_input}:**")
                file_links = st.session_state['vault'].get(sub_input, {}).get("file_links", {})
                for f in prev_files:
                    if f in file_links and file_links[f]:
                        st.markdown(f"- [{f}]({file_links[f]})")
                    else:
                        st.markdown(f"- {f}")
            
            opt1, opt2 = st.tabs(["📄 Upload Additional PDF", "✍️ Manual Topics"])
            with opt1:
                up_files = st.file_uploader("Upload Study Material", type="pdf", accept_multiple_files=True)
                if st.button("Extract & Save"):
                    if up_files and sub_input:
                        with st.spinner("Vaulting content and syncing to free cloud folder..."):
                            if "files" not in st.session_state['vault'][sub_input]: st.session_state['vault'][sub_input]["files"] = []
                            if "file_chapter_mapping" not in st.session_state['vault'][sub_input]: st.session_state['vault'][sub_input]["file_chapter_mapping"] = {}
                            if "file_links" not in st.session_state['vault'][sub_input]: st.session_state['vault'][sub_input]["file_links"] = {}
                            
                            for f in up_files:
                                t = extract_index_text(f.getvalue())
                                
                                if len(t.strip()) < 50:
                                    st.error(f"❌ '{f.name}' appears to be a scanned image PDF. Please upload a digital text PDF.")
                                    continue
                                
                                ch = get_chapters_from_ai(t, sub_input)
                                
                                if not ch:
                                    st.warning(f"⚠️ AI couldn't detect index in '{f.name}'. Content saved, but chapters must be manually assigned.")
                                else:
                                    st.session_state['vault'][sub_input]["file_chapter_mapping"][f.name] = ch
                                    st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + ch))
                                    
                                cloud_link = upload_pdf_to_dropbox(f.getvalue(), f.name)
                                if cloud_link:
                                    st.session_state['vault'][sub_input]["file_links"][f.name] = cloud_link
                                    st.success(f"✅ Extracted chapters and saved '{f.name}' to Cloud!")
                                else:
                                    st.warning(f"⚠️ Chapters saved, but physical file could not be uploaded.")

                                st.session_state['vault'][sub_input]["content"] += "\n" + t
                                st.session_state['vault'][sub_input]["files"].append(f.name)
                                time.sleep(1)
                                
                            st.session_state['vault'][sub_input]["files"] = list(set(st.session_state['vault'][sub_input]["files"]))
                            save_data()
                            time.sleep(1)
                            st.rerun()
                            
            with opt2:
                man_chaps = st.text_area("Paste topics (one per line):")
                if st.button("Add Topics"):
                    if man_chaps and sub_input:
                        new_c = [c.strip() for c in man_chaps.split('\n') if c.strip()]
                        if "manual_chapters" not in st.session_state['vault'][sub_input]:
                            st.session_state['vault'][sub_input]["manual_chapters"] = []
                        st.session_state['vault'][sub_input]["manual_chapters"] = list(set(st.session_state['vault'][sub_input]["manual_chapters"] + new_c))
                        st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + new_c))
                        save_data()
                        st.success("Topics committed successfully!")
                        time.sleep(1)
                        st.rerun()

        st.header("2. Build Custom Deck")
        if sub_input == "All Subjects":
            chaps = []
            for s in existing_subs: chaps.extend(get_active_chapters(s))
            chaps = sorted(list(set(chaps)))
        else:
            chaps = get_active_chapters(sub_input)
            
        select_all = st.checkbox("Select All Chapters")
        sel_chaps = chaps if select_all else st.multiselect("Select Topics:", options=chaps)
            
        diff = st.selectbox("Difficulty:", ["Easy", "Moderate", "Hard", "UPSC Level"])
        q_vol = st.slider("Total Questions:", 5, 25, 10)
        t_limit = st.number_input("Timer (Mins):", 1, 60, q_vol)
        
        st.markdown("**Custom Scoring Parameters:**")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            marks_per_q = st.number_input("Marks per Correct:", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
        with col_m2:
            neg_mark_val = st.number_input("Negative Penalty:", min_value=0.0, max_value=5.0, value=0.66, step=0.01)

        st.write("---")
        force_revision = st.checkbox("🔄 Revision Mode (Bypass AI & Quotas. Use Question Bank Only)", value=False)

        if st.button("Generate Question Deck 🔥"):
            if sel_chaps:
                with st.spinner("Compiling comprehensive questions..."):
                    if sub_input == "All Subjects": v_text = "\n".join([st.session_state['vault'][s].get("content", "") for s in existing_subs])
                    else: v_text = st.session_state['vault'][sub_input].get("content", "")
                        
                    matching_old = [q for q in st.session_state['old_questions'] if q.get('chapter') in sel_chaps]
                    
                    if force_revision:
                        if len(matching_old) < q_vol:
                            st.warning(f"You only have {len(matching_old)} questions saved for these topics. Building test with available questions.")
                        mix_count = min(len(matching_old), q_vol)
                        fresh_needed = 0
                        qs = [] 
                    else:
                        mix_count = min(len(matching_old), max(1, q_vol // 2)) if matching_old else 0
                        fresh_needed = q_vol - mix_count
                        qs = generate_new_questions(sub_input, sel_chaps, diff, fresh_needed, ["Single Correct MCQ", "Statement Based"], v_text)
                    
                    if qs or mix_count > 0:
                        for q in qs:
                            q['subject'] = sub_input
                            q['difficulty'] = diff
                            
                        if qs:
                            st.session_state['old_questions'].extend(qs)
                            save_data()
                        
                        pool = qs
                        if mix_count > 0: pool += random.sample(matching_old, mix_count)
                        random.shuffle(pool)
                        
                        st.session_state['active_quiz'] = pool
                        st.session_state['quiz_submitted'] = False
                        st.session_state['test_start_time'] = time.time()
                        st.session_state['target_duration'] = t_limit * 60
                        st.session_state['test_config'] = {"marks": marks_per_q, "penalty": neg_mark_val}
                        st.rerun()
                    else:
                        st.error("No questions available. Either generate new ones with AI (check your quota) or select chapters you have previously tested.")
            else:
                st.error("Please select at least one chapter.")

    with col2:
        st.header("3. Examination Chamber")
        if st.session_state['active_quiz']:
            if not st.session_state['quiz_submitted']:
                rem = max(0, int(st.session_state.get('target_duration', 600) - (time.time() - st.session_state.get('test_start_time', time.time()))))
                
                timer_html = f"""
                <div style="font-family: sans-serif; font-size: 24px; font-weight: bold; color: #ff4b4b; background-color: #ffeaea; border: 2px solid #ff4b4b; border-radius: 8px; padding: 10px; text-align: center; margin-bottom: 20px;">
                    ⏱️ Time Remaining: <span id="clock"></span>
                </div>
                <script>
                    var timeLeft = {rem};
                    var display = document.getElementById('clock');
                    var timerId = setInterval(function () {{
                        if (timeLeft >= 0) {{
                            var m = Math.floor(timeLeft / 60).toString().padStart(2, '0');
                            var s = (timeLeft % 60).toString().padStart(2, '0');
                            display.textContent = m + ":" + s;
                            timeLeft--;
                        }} else {{
                            clearInterval(timerId);
                            display.textContent = "TIME UP! Please Submit.";
                        }}
                    }}, 1000);
                </script>
                """
                components.html(timer_html, height=80)
            
            ans = {}
            for i, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"**Q{i+1}.** <span style='color:#007BFF;'>[{q.get('type', 'MCQ')}]</span> {q['question']}", unsafe_allow_html=True)
                ans[i] = st.radio(f"Opt {i}", options=["Skip"] + [f"{k}) {v}" for k,v in q['options'].items()], key=f"q{i}", label_visibility="collapsed")
                st.write("")

            if not st.session_state['quiz_submitted']:
                if st.button("Submit Assessment & Evaluate", type="primary"):
                    st.session_state['quiz_submitted'] = True
                    correct, wrong, skipped = 0, 0, 0
                    c_perf = {c: {"correct": 0, "incorrect": 0} for c in sel_chaps}
                    wrong_details = []
                    
                    config = st.session_state['test_config']
                    
                    for i, q in enumerate(st.session_state['active_quiz']):
                        qc = q.get('chapter', 'General')
                        if qc not in c_perf: c_perf[qc] = {"correct": 0, "incorrect": 0}
                        
                        is_correct = False
                        if ans[i] == "Skip": 
                            skipped += 1
                        elif ans[i].startswith(q['correct']): 
                            correct += 1
                            c_perf[qc]["correct"] += 1
                            is_correct = True
                        else: 
                            wrong += 1
                            c_perf[qc]["incorrect"] += 1
                            wrong_details.append({"chapter": qc, "question": q['question'], "explanation": q['explanation']})
                            
                        for oq in st.session_state['old_questions']:
                            if oq.get('id') == q.get('id'):
                                oq['last_attempt_correct'] = is_correct
                                break
                            
                    net = (correct * config['marks']) - (wrong * config['penalty'])
                    
                    test_count = len([x for x in st.session_state['quiz_history_log'] if x.get('subject') == sub_input]) + 1
                    ist_now = get_ist_time()
                    timestamp_full = ist_now.strftime("%d %b %Y, %I:%M %p")
                    timestamp_compact = ist_now.strftime("%d%b_%I%M%p")
                    test_name_formatted = f"{sub_input}_Test_{test_count}_{timestamp_compact}"
                    
                    for q in st.session_state['active_quiz']:
                        for oq in st.session_state['old_questions']:
                            if oq.get('id') == q.get('id'):
                                oq['test_ref'] = test_name_formatted
                                break

                    st.session_state['quiz_history_log'].append({
                        "subject": sub_input,
                        "test_name": test_name_formatted,
                        "date_str": timestamp_full,
                        "correct": correct, "incorrect": wrong, "skipped": skipped,
                        "net": round(net, 2), "total_items": len(st.session_state['active_quiz']),
                        "penalty": round((wrong * config['penalty']), 2),
                        "chapter_perf": c_perf,
                        "wrong_details": wrong_details
                    })
                    save_data()
                    st.rerun()
            else:
                st.success("📝 Evaluation Complete")
                log = st.session_state['quiz_history_log'][-1]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Correct", f"✅ {log.get('correct',0)}")
                m2.metric("Negative", f"❌ -{log.get('penalty',0)}")
                m3.metric("Skipped", f"⚪ {log.get('skipped',0)}")
                m4.metric("Net Marks", f"🎯 {log.get('net',0)}")
                
                md_out = build_markdown_export(st.session_state['active_quiz'], sub_input)
                st.download_button("📄 Export Practice Set", data=md_out, file_name=f"{log.get('test_name')}.md", mime="text/markdown")
                
                st.write("---")
                for i, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Q{i+1}:** {q['question']}")
                    for k, v in q['options'].items():
                        if k == q['correct']: st.markdown(f"🟩 **{k}) {v} (Correct Key)**")
                        elif ans[i].startswith(k) and ans[i] != "Skip": st.markdown(f"🟥 **{k}) {v} (Your Pick)**")
                        else: st.markdown(f"⚪ {k}) {v}")
                    with st.expander("📘 Comprehensive Topic Mastery (Complete Revision)"):
                        st.markdown(f"{q['explanation']}")
                        st.markdown(f"💡 *Strategic Point:* {q.get('extra_info','')}")
                
                if st.button("Reload Simulator"):
                    st.session_state['active_quiz'] = None
                    st.session_state['quiz_submitted'] = False
                    st.rerun()

with tab_analytics:
    st.header("📊 Performance Analytics Hub")
    subjects = list(st.session_state['vault'].keys())
    if "All Subjects" in subjects: subjects.remove("All Subjects")
    
    if not st.session_state['quiz_history_log']:
        st.info("Performance dashboards will generate dynamically after your first test.")
    else:
        tabs = st.tabs(["Overall Summary"] + subjects)
        
        with tabs[0]:
            st.subheader("Global Command Center")
            df = pd.DataFrame(st.session_state['quiz_history_log'])
            if not df.empty:
                cm1, cm2 = st.columns(2)
                cm1.metric("Total Tests Taken", len(df))
                cm2.metric("Average Net Score", f"{df['net'].mean():.2f}")
                
                st.write("---")
                st.subheader("Subject-Wise Master Analytics")
                
                for sub in df['subject'].unique():
                    sub_df = df[df['subject'] == sub]
                    
                    agg_c_perf = {}
                    t_cor = sub_df['correct'].sum()
                    t_wrg = sub_df['incorrect'].sum()
                    t_skp = sub_df['skipped'].sum()
                    
                    for perf in sub_df['chapter_perf']:
                        if isinstance(perf, dict):
                            for ch, metrics in perf.items():
                                if ch not in agg_c_perf: agg_c_perf[ch] = {"correct": 0, "incorrect": 0}
                                agg_c_perf[ch]["correct"] += metrics.get("correct", 0)
                                agg_c_perf[ch]["incorrect"] += metrics.get("incorrect", 0)
                    
                    chap_accuracies = []
                    for ch, met in agg_c_perf.items():
                        tot = met['correct'] + met['incorrect']
                        if tot > 0:
                            acc = (met['correct'] / tot) * 100
                            chap_accuracies.append((ch, acc))
                            
                    chap_accuracies.sort(key=lambda x: x[1]) 
                    top_3_weakest = chap_accuracies[:3]
                                
                    with st.container():
                        st.markdown(f"#### 📚 {sub} ({len(get_active_chapters(sub))} Chapters)")
                        sc1, sc2 = st.columns([1, 1])
                        with sc1:
                            st.write(f"**Tests Taken:** {len(sub_df)}")
                            st.write(f"**Average Score:** {sub_df['net'].mean():.2f}")
                            
                            if top_3_weakest:
                                st.error("🚨 **Top 3 Areas to Revise:**")
                                for rank, (wc, wacc) in enumerate(top_3_weakest):
                                    st.write(f"{rank+1}. **{wc}** *(Accuracy: {wacc:.1f}%)*")
                            else:
                                st.info("Need more test data for detailed weakness analytics.")
                        with sc2:
                            pie_df = pd.DataFrame({"Outcome": ["Correct", "Wrong", "Skipped"], "Count": [t_cor, t_wrg, t_skp]})
                            fig = px.pie(pie_df, values='Count', names='Outcome', color='Outcome', color_discrete_map={"Correct": "green", "Wrong": "red", "Skipped": "gray"})
                            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200)
                            st.plotly_chart(fig, use_container_width=True)
                        st.divider()
            
        for i, sub in enumerate(subjects):
            with tabs[i+1]:
                logs = [l for l in st.session_state['quiz_history_log'] if l.get('subject') == sub]
                if not logs: st.write("No tests recorded yet.")
                else:
                    for log in reversed(logs):
                        date_display = log.get('date_str', 'Unknown Date')
                        with st.expander(f"📋 {log.get('test_name')} - {date_display}", expanded=False):
                            cA, cB = st.columns([1, 1])
                            with cA:
                                st.markdown("### Score Matrix")
                                st.write(f"**Total Questions:** {log.get('total_items', 0)}")
                                st.write(f"✅ **Right:** {log.get('correct',0)}")
                                st.write(f"❌ **Wrong:** {log.get('incorrect',0)}")
                                st.markdown(f"#### 🎯 Net Marks: {log.get('net',0)}")
                                
                                c_perf = log.get('chapter_perf', {})
                                if c_perf:
                                    st.markdown("### Area Analysis")
                                    b_c, w_c, mx, mn = "N/A", "N/A", -1, 101
                                    for c, met in c_perf.items():
                                        tot = met['correct'] + met['incorrect']
                                        if tot > 0:
                                            acc = (met['correct'] / tot) * 100
                                            if acc > mx: mx, b_c = acc, c
                                            if acc < mn: mn, w_c = acc, c
                                    st.success(f"🌟 **Strong Area:** {b_c}")
                                    st.error(f"📉 **Needs Work:** {w_c}")
                                    
                                    if w_c != "N/A":
                                        wrong_in_worst = [wq for wq in log.get('wrong_details', []) if wq['chapter'] == w_c]
                                        if wrong_in_worst:
                                            with st.expander(f"🔍 Instant Review: Errors in '{w_c}'"):
                                                for wq in wrong_in_worst:
                                                    st.markdown(f"**Q:** {wq['question']}")
                                                    st.info(f"**Concept:** {wq['explanation']}")
                                                    st.write("---")

                            with cB:
                                ch_df = pd.DataFrame({"Outcome": ["Correct", "Wrong", "Skipped"], "Count": [log.get('correct',0), log.get('incorrect',0), log.get('skipped',0)]})
                                fig = px.pie(ch_df, values='Count', names='Outcome', color='Outcome', color_discrete_map={"Correct": "green", "Wrong": "red", "Skipped": "gray"})
                                fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
                                st.plotly_chart(fig, use_container_width=True)

with tab_history:
    st.header("🗄️ Master Question Repository")
    if st.session_state['old_questions']:
        subjects_in_bank = list(set([q.get('subject', 'General') for q in st.session_state['old_questions']]))
        qb_tabs = st.tabs(subjects_in_bank)
        
        for idx, s_tab in enumerate(subjects_in_bank):
            with qb_tabs[idx]:
                sub_qs = [q for q in st.session_state['old_questions'] if q.get('subject') == s_tab]
                chapters_in_sub = sorted(list(set([q.get('chapter', 'General Review') for q in sub_qs])))
                
                st.write(f"**Total Database Questions for {s_tab}: {len(sub_qs)}**")
                
                for chap in chapters_in_sub:
                    chap_qs = [q for q in sub_qs if q.get('chapter', 'General Review') == chap]
                    right_qs = [q for q in chap_qs if q.get('last_attempt_correct') == True]
                    wrong_qs = [q for q in chap_qs if q.get('last_attempt_correct') in [False, None]]
                    
                    with st.expander(f"📖 {chap} (Total: {len(chap_qs)} | ✅ {len(right_qs)} | ❌ {len(wrong_qs)})"):
                        rt_tab, wt_tab = st.tabs([f"✅ Mastered ({len(right_qs)})", f"❌ Needs Revision ({len(wrong_qs)})"])
                        
                        with wt_tab:
                            for item in reversed(wrong_qs):
                                st.markdown(f"**[{item.get('test_ref', 'Bank')}]** {item['question']}")
                                for k, v in item['options'].items():
                                    mark = "🟩" if k == item['correct'] else "⚪"
                                    st.write(f"{mark} {k}) {v}")
                                st.info(f"**Explanation:** {item['explanation']}")
                                st.write("---")
                                
                        with rt_tab:
                            for item in reversed(right_qs):
                                st.markdown(f"**[{item.get('test_ref', 'Bank')}]** {item['question']}")
                                st.success(f"Correct Answer: {item['correct']} - {item['options'].get(item['correct'])}")
                                st.write("---")
    else:
        st.write("Storage registers empty.")

with tab_settings:
    st.header("⚙️ Vault Management & Database Control")
    
    if "recycle_bin" not in st.session_state:
        st.session_state["recycle_bin"] = {"subjects": {}, "chapters": {}, "files": {}}
        
    t1, t2, t3 = st.tabs(["🗑️ Data Shredder", "💾 Cloud Backups", "✏️ Rename Vault Items"])
    
    with t1:
        st.subheader("Delete and Move Content to Recycle Bin")
        st.write("Deleting content transfers it securely into the Recycle panel below so it can be recovered later.")
        
        del_c1, del_c2, del_c3 = st.columns(3)
        subs_list = list(st.session_state['vault'].keys())
        
        with del_c1:
            st.markdown("**1. Shred Entire Subject**")
            if subs_list:
                sel_sub_del = st.selectbox("Choose Target Subject:", subs_list, key="sb_del_select")
                if st.button("Trash Subject", type="primary"):
                    st.session_state['recycle_bin']["subjects"][sel_sub_del] = st.session_state['vault'][sel_sub_del]
                    del st.session_state['vault'][sel_sub_del]
                    save_data()
                    st.success(f"Moved {sel_sub_del} to Recycle Bin.")
                    time.sleep(1)
                    st.rerun()
            else: st.info("No active subjects.")
                
        with del_c2:
            st.markdown("**2. Shred Specific Chapter**")
            if subs_list:
                sel_sub_chap = st.selectbox("Choose Parent Subject:", subs_list, key="ch_del_sub_select")
                chaps_list = sorted(st.session_state['vault'].get(sel_sub_chap, {}).get("chapters", []))
                if chaps_list:
                    sel_chap_del = st.selectbox("Choose Chapter to Trash:", chaps_list, key="ch_del_select")
                    if st.button("Trash Chapter"):
                        if sel_sub_chap not in st.session_state['recycle_bin']["chapters"]:
                            st.session_state['recycle_bin']["chapters"][sel_sub_chap] = []
                        st.session_state['recycle_bin']["chapters"][sel_sub_chap].append(sel_chap_del)
                        
                        if sel_chap_del in st.session_state['vault'][sel_sub_chap].get("manual_chapters", []):
                            st.session_state['vault'][sel_sub_chap]["manual_chapters"].remove(sel_chap_del)
                        if sel_chap_del in st.session_state['vault'][sel_sub_chap].get("chapters", []):
                            st.session_state['vault'][sel_sub_chap]["chapters"].remove(sel_chap_del)
                            
                        save_data()
                        st.success("Moved chapter to Recycle Bin.")
                        time.sleep(1)
                        st.rerun()
                else: st.info("No chapters in this subject.")
                    
        with del_c3:
            st.markdown("**3. Shred PDF link**")
            if subs_list:
                sel_sub_file = st.selectbox("Choose Parent Subject:", subs_list, key="f_del_sub_select")
                files_list = st.session_state['vault'].get(sel_sub_file, {}).get("files", [])
                if files_list:
                    sel_f_del = st.selectbox("Choose PDF to Trash:", files_list, key="f_del_select")
                    if st.button("Trash PDF Reference"):
                        if sel_sub_file not in st.session_state['recycle_bin']["files"]:
                            st.session_state['recycle_bin']["files"][sel_sub_file] = []
                            
                        file_chaps = st.session_state['vault'][sel_sub_file].get("file_chapter_mapping", {}).get(sel_f_del, [])
                        file_link = st.session_state['vault'][sel_sub_file].get("file_links", {}).get(sel_f_del, "")
                        
                        st.session_state['recycle_bin']["files"][sel_sub_file].append({
                            "name": sel_f_del, 
                            "mapped_chapters": file_chaps,
                            "dropbox_link": file_link
                        })
                        
                        st.session_state['vault'][sel_sub_file]["files"].remove(sel_f_del)
                        if sel_f_del in st.session_state['vault'][sel_sub_file].get("file_chapter_mapping", {}):
                            del st.session_state['vault'][sel_sub_file]["file_chapter_mapping"][sel_f_del]
                        if sel_f_del in st.session_state['vault'][sel_sub_file].get("file_links", {}):
                            del st.session_state['vault'][sel_sub_file]["file_links"][sel_f_del]
                            
                        save_data()
                        st.success("Moved file link and its mapped chapters to Recycle Bin.")
                        time.sleep(1)
                        st.rerun()
                else: st.info("No active files links attached.")
                
        st.write("---")
        st.subheader("♻️ The Recycle Recovery Vault")
        st.write("Select any previously deleted components to restore them completely back to your active study loop.")
        
        rec_c1, rec_c2, rec_c3 = st.columns(3)
        
        with rec_c1:
            st.markdown("**Restore Trashed Subjects**")
            deleted_subs = list(st.session_state['recycle_bin'].get("subjects", {}).keys())
            if deleted_subs:
                sub_to_restore = st.selectbox("Select Subject to Recover:", deleted_subs)
                if st.button("Recover Subject", type="primary"):
                    st.session_state['vault'][sub_to_restore] = st.session_state['recycle_bin']["subjects"][sub_to_restore]
                    del st.session_state['recycle_bin']["subjects"][sub_to_restore]
                    save_data()
                    st.success(f"Successfully restored {sub_to_restore}!")
                    time.sleep(1)
                    st.rerun()
            else: st.caption("Subject bin empty.")
                
        with rec_c2:
            st.markdown("**Restore Trashed Chapters**")
            sub_ch_bin = list(st.session_state['recycle_bin'].get("chapters", {}).keys())
            active_sub_ch_bin = [s for s in sub_ch_bin if st.session_state['recycle_bin']["chapters"][s]]
            if active_sub_ch_bin:
                r_sub_c = st.selectbox("Choose Subject context:", active_sub_ch_bin)
                r_chap = st.selectbox("Select Chapter to Recover:", st.session_state['recycle_bin']["chapters"][r_sub_c])
                if st.button("Recover Chapter"):
                    if r_sub_c in st.session_state['vault']:
                        if "manual_chapters" not in st.session_state['vault'][r_sub_c]:
                            st.session_state['vault'][r_sub_c]["manual_chapters"] = []
                        st.session_state['vault'][r_sub_c]["manual_chapters"].append(r_chap)
                        st.session_state['vault'][r_sub_c]["chapters"].append(r_chap)
                        st.session_state['recycle_bin']["chapters"][r_sub_c].remove(r_chap)
                        save_data()
                        st.success(f"Restored chapter back to {r_sub_c}!")
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Parent subject structure missing. Recover the subject first.")
            else: st.caption("Chapter bin empty.")
                
        with rec_c3:
            st.markdown("**Restore Trashed PDF Links**")
            sub_f_bin = list(st.session_state['recycle_bin'].get("files", {}).keys())
            active_sub_f_bin = [s for s in sub_f_bin if st.session_state['recycle_bin']["files"][s]]
            if active_sub_f_bin:
                r_sub_f = st.selectbox("Choose Subject context:", active_sub_f_bin, key="rec_f_sub")
                
                raw_bin_options = st.session_state['recycle_bin']["files"][r_sub_f]
                formatted_options = [f["name"] if isinstance(f, dict) else f for f in raw_bin_options]
                
                selected_f_name = st.selectbox("Select PDF to Recover:", formatted_options)
                
                if st.button("Recover PDF link"):
                    if r_sub_f in st.session_state['vault']:
                        if "file_chapter_mapping" not in st.session_state['vault'][r_sub_f]:
                            st.session_state['vault'][r_sub_f]["file_chapter_mapping"] = {}
                        if "file_links" not in st.session_state['vault'][r_sub_f]:
                            st.session_state['vault'][r_sub_f]["file_links"] = {}
                        
                        target_element = {"name": selected_f_name, "mapped_chapters": [], "dropbox_link": ""}
                        for item in raw_bin_options:
                            if isinstance(item, dict) and item["name"] == selected_f_name:
                                target_element = item
                                break
                            elif isinstance(item, str) and item == selected_f_name:
                                target_element = {"name": item, "mapped_chapters": [], "dropbox_link": ""}
                                break
                        
                        st.session_state['vault'][r_sub_f]["files"].append(selected_f_name)
                        st.session_state['vault'][r_sub_f]["file_chapter_mapping"][selected_f_name] = target_element["mapped_chapters"]
                        
                        if target_element.get("dropbox_link"):
                            st.session_state['vault'][r_sub_f]["file_links"][selected_f_name] = target_element["dropbox_link"]
                        
                        st.session_state['recycle_bin']["files"][r_sub_f].remove(item)
                        save_data()
                        st.success(f"Linked reference file and restored its chapters back to {r_sub_f}!")
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Parent subject structure missing.")
            else: st.caption("File link bin empty.")

    with t2:
        st.subheader("💾 Hard Drive Backups")
        col_dl, col_ul = st.columns(2)
        with col_dl:
            if os.path.exists(DB_FILE):
                st.download_button(
                    label="📥 Download Database Backup", 
                    data=json.dumps(get_clean_data()), 
                    file_name=f"BPSC_Backup_{datetime.datetime.now().strftime('%Y-%m-%d')}.json", 
                    mime="application/json", 
                    type="primary"
                )
            else: st.info("No database file found to backup yet.")
            
        with col_ul:
            restore_file = st.file_uploader("📤 Restore from Backup File", type="json")
            if restore_file is not None:
                if st.button("Restore Database"):
                    try:
                        uploaded_data = json.loads(restore_file.getvalue())
                        st.session_state['vault'] = uploaded_data.get('vault', {})
                        st.session_state['old_questions'] = uploaded_data.get('old_questions', [])
                        st.session_state['quiz_history_log'] = uploaded_data.get('quiz_history_log', [])
                        st.session_state['recycle_bin'] = uploaded_data.get('recycle_bin', {"subjects": {}, "chapters": {}, "files": {}})
                        save_data()
                        st.success("Database restored successfully! The app will now refresh.")
                        time.sleep(2)
                        st.rerun()
                    except Exception: st.error("Invalid backup file.")

    with t3:
        st.subheader("✏️ Mass Rename Subjects & Chapters")
        st.write("Update names here and the system will automatically relink your entire Question Bank and Analytics history to the new name.")
        
        ren_col1, ren_col2 = st.columns(2)
        subs_list_ren = list(st.session_state['vault'].keys())
        
        with ren_col1:
            st.markdown("**1. Rename an Entire Subject**")
            if subs_list_ren:
                old_sub = st.selectbox("Select Subject to Rename:", subs_list_ren, key="ren_sub_sel")
                new_sub = st.text_input("Enter New Subject Name:", key="ren_sub_input")
                if st.button("Update Subject Name", type="primary"):
                    if new_sub and new_sub != old_sub and new_sub not in st.session_state['vault']:
                        st.session_state['vault'][new_sub] = st.session_state['vault'].pop(old_sub)
                        for q in st.session_state['old_questions']:
                            if q.get('subject') == old_sub: q['subject'] = new_sub
                        for log in st.session_state['quiz_history_log']:
                            if log.get('subject') == old_sub: log['subject'] = new_sub
                        save_data()
                        st.success(f"Renamed '{old_sub}' to '{new_sub}'!")
                        time.sleep(1)
                        st.rerun()
                    elif new_sub in st.session_state['vault']:
                        st.error("A subject with that name already exists.")
            else: st.info("No active subjects.")
                
        with ren_col2:
            st.markdown("**2. Rename a Specific Chapter**")
            if subs_list_ren:
                target_sub = st.selectbox("Select Parent Subject:", subs_list_ren, key="ren_chap_sub")
                chaps_list_ren = sorted(get_active_chapters(target_sub))
                if chaps_list_ren:
                    old_chap = st.selectbox("Select Chapter to Rename:", chaps_list_ren, key="ren_chap_sel")
                    new_chap = st.text_input("Enter New Chapter Name:", key="ren_chap_input")
                    if st.button("Update Chapter Name"):
                        if new_chap and new_chap != old_chap:
                            v = st.session_state['vault'][target_sub]
                            if old_chap in v.get("chapters", []):
                                v["chapters"] = [new_chap if c == old_chap else c for c in v["chapters"]]
                            if old_chap in v.get("manual_chapters", []):
                                v["manual_chapters"] = [new_chap if c == old_chap else c for c in v["manual_chapters"]]
                            for f, chaps in v.get("file_chapter_mapping", {}).items():
                                v["file_chapter_mapping"][f] = [new_chap if c == old_chap else c for c in chaps]
                                
                            for q in st.session_state['old_questions']:
                                if q.get('subject') == target_sub and q.get('chapter') == old_chap:
                                    q['chapter'] = new_chap
                                    
                            for log in st.session_state['quiz_history_log']:
                                if log.get('subject') == target_sub:
                                    if old_chap in log.get('chapter_perf', {}):
                                        log['chapter_perf'][new_chap] = log['chapter_perf'].pop(old_chap)
                                    for w in log.get('wrong_details', []):
                                        if w.get('chapter') == old_chap: w['chapter'] = new_chap
                                        
                            save_data()
                            st.success(f"Renamed '{old_chap}' to '{new_chap}'!")
                            time.sleep(1)
                            st.rerun()
                else: st.info("No active chapters in this subject.")
