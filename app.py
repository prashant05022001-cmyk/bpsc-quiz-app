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

# --- PAGE SETUP ---
st.set_page_config(page_title="Civil Services Smart Quiz Dashboard", page_icon="📚", layout="wide")

# --- PERMANENT STORAGE DATABASE SYSTEM ---
DB_FILE = "database.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "vault": {},
        "old_questions": [],
        "quiz_history_log": []
    }

def save_data():
    data_to_save = {
        "vault": st.session_state['vault'],
        "old_questions": st.session_state['old_questions'],
        "quiz_history_log": st.session_state['quiz_history_log']
    }
    with open(DB_FILE, "w") as f:
        json.dump(data_to_save, f)

if 'db_loaded' not in st.session_state:
    saved_data = load_data()
    st.session_state['vault'] = saved_data.get('vault', {})
    st.session_state['old_questions'] = saved_data.get('old_questions', [])
    st.session_state['quiz_history_log'] = saved_data.get('quiz_history_log', [])
    st.session_state['db_loaded'] = True

if 'active_quiz' not in st.session_state: st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state: st.session_state['quiz_submitted'] = False

# --- API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- HELPERS ---
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

def get_chapters_from_ai(text, subject_name, retries=2):
    prompt = f"Extract chapter names from this {subject_name} index. Return ONLY a JSON array of strings."
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt + f"\nText: {text[:10000]}", generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e): time.sleep(15)
            else: return []
    return []

def generate_new_questions(subject, chapters, difficulty, count, item_types, vault_full_text, retries=2):
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
    Return JSON array exactly:
    [ {{"id": 1234, "type": "MCQ", "chapter": "{chapters[0]}", "question": "Q?", "options": {{"A": "1", "B": "2", "C": "3", "D": "4"}}, "correct": "A", "explanation": "Exp.", "extra_info": "Fact."}} ]
    """
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                st.warning("Speed limit hit. AI is pausing. Retrying in 20s...")
                time.sleep(20)
            else: return []
    return []

def build_markdown_export(quiz_pool, subject):
    md = f"# Practice Set: {subject}\n\n"
    for idx, q in enumerate(quiz_pool):
        md += f"### Q{idx+1} [{q.get('type', 'MCQ')}] ({q.get('chapter', '')})\n{q['question']}\n\n"
        for k, v in q['options'].items(): md += f"- **{k}**: {v}\n"
        md += f"\n**Correct:** {q['correct']} | **Explanation:** {q['explanation']}\n\n---\n"
    return md

# --- APP LAYOUT ---
st.title("📚 Civil Services Smart Quiz Dashboard")
st.write("---")

tab_quiz, tab_analytics, tab_history, tab_settings = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "🗄️ Question Bank", "⚙️ Vault Backup"])

with tab_quiz:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.header("1. Sync Content Vault")
        existing_subs = list(st.session_state['vault'].keys())
        
        sub_options = ["All Subjects"] + existing_subs if existing_subs else []
        sub_mode = st.radio("Mode:", ["Existing Subject", "New Subject"])
        
        if sub_mode == "Existing Subject" and sub_options:
            sub_input = st.selectbox("Subject:", options=sub_options)
        else:
            sub_input = st.text_input("New Subject:")
        
        if sub_input and sub_input != "All Subjects" and sub_input not in st.session_state['vault']:
            # Initialize with 'files' array to track uploaded PDFs
            st.session_state['vault'][sub_input] = {"chapters": [], "content": "", "files": []}
            save_data()

        st.write("---")
        if sub_input != "All Subjects":
            # FEATURE 1: Show previously uploaded PDFs
            prev_files = st.session_state['vault'].get(sub_input, {}).get("files", [])
            if prev_files:
                st.info(f"📁 **Active PDFs stored for {sub_input}:**\n" + "\n".join([f"- {f}" for f in prev_files]))
                st.write("*Do you want to add additional study material?*")
            else:
                st.write("*No PDFs uploaded for this subject yet.*")

            opt1, opt2 = st.tabs(["📄 Upload Additional PDF", "✍️ Manual Topics"])
            with opt1:
                up_files = st.file_uploader("Upload Study Material (Saved Permanently)", type="pdf", accept_multiple_files=True)
                if st.button("Extract & Save to Vault"):
                    if up_files and sub_input:
                        with st.spinner("Vaulting content safely..."):
                            if "files" not in st.session_state['vault'][sub_input]:
                                st.session_state['vault'][sub_input]["files"] = []
                                
                            for f in up_files:
                                t = extract_index_text(f.getvalue())
                                ch = get_chapters_from_ai(t, sub_input)
                                st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + ch))
                                st.session_state['vault'][sub_input]["content"] += "\n" + t
                                st.session_state['vault'][sub_input]["files"].append(f.name) # Track the file name!
                                time.sleep(4)
                                
                            # Remove duplicates in file list
                            st.session_state['vault'][sub_input]["files"] = list(set(st.session_state['vault'][sub_input]["files"]))
                            save_data()
                            st.success("Files saved safely to your Hard Drive!")
                            st.rerun()
            with opt2:
                man_chaps = st.text_area("Paste topics (one per line):")
                if st.button("Add Topics"):
                    if man_chaps and sub_input:
                        new_c = [c.strip() for c in man_chaps.split('\n') if c.strip()]
                        st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + new_c))
                        save_data()
                        st.success("Topics saved!")
                        st.rerun()

        st.header("2. Build Custom Deck")
        if sub_input == "All Subjects":
            chaps = []
            for s in existing_subs:
                chaps.extend(st.session_state['vault'][s].get("chapters", []))
        else:
            chaps = st.session_state['vault'].get(sub_input, {}).get("chapters", [])
            
        select_all = st.checkbox("Select All Chapters")
        if select_all:
            sel_chaps = chaps
            st.success(f"All {len(chaps)} chapters selected.")
        else:
            sel_chaps = st.multiselect("Select Topics:", options=chaps)
            
        diff = st.selectbox("Difficulty:", ["Moderate", "Hard", "UPSC Level"])
        q_vol = st.slider("Questions:", 5, 20, 10)
        t_limit = st.number_input("Timer (Mins):", 1, 60, q_vol)
        neg_mark = st.checkbox("Negative Marking (1/3rd)", True)
        
        selected_patterns = ["Single Correct MCQ", "Statement Based"]

        if st.button("Generate Question Deck 🔥"):
            if sel_chaps:
                with st.spinner("Compiling questions..."):
                    if sub_input == "All Subjects":
                        v_text = "\n".join([st.session_state['vault'][s].get("content", "") for s in existing_subs])
                    else:
                        v_text = st.session_state['vault'][sub_input].get("content", "")
                        
                    matching_old = [q for q in st.session_state['old_questions'] if q.get('chapter') in sel_chaps]
                    mix_count = min(len(matching_old), max(1, q_vol // 3)) if matching_old else 0
                    fresh_needed = q_vol - mix_count
                    
                    # Generate test identifier for tracking
                    test_count = len([x for x in st.session_state['quiz_history_log'] if x.get('subject') == sub_input]) + 1
                    test_ref_id = f"{sub_input}_Test_{test_count}"
                    
                    qs = generate_new_questions(sub_input, sel_chaps, diff, fresh_needed, selected_patterns, v_text)
                    
                    if qs or mix_count > 0:
                        for q in qs:
                            q['subject'] = sub_input
                            q['difficulty'] = diff
                            q['test_ref'] = test_ref_id # Tag the question with its Test Number
                            
                        st.session_state['old_questions'].extend(qs)
                        save_data()
                        
                        pool = qs
                        if mix_count > 0: pool += random.sample(matching_old, mix_count)
                        random.shuffle(pool)
                        
                        st.session_state['active_quiz'] = pool
                        st.session_state['quiz_submitted'] = False
                        st.session_state['test_start_time'] = time.time()
                        st.session_state['target_duration'] = t_limit * 60
                        st.rerun()
                    else:
                        st.error("Generation timed out. Google AI Quota reached. Try again later.")
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
                    
                    for i, q in enumerate(st.session_state['active_quiz']):
                        qc = q.get('chapter', 'General')
                        if qc not in c_perf: c_perf[qc] = {"correct": 0, "incorrect": 0}
                        if ans[i] == "Skip": skipped += 1
                        elif ans[i].startswith(q['correct']): 
                            correct += 1
                            c_perf[qc]["correct"] += 1
                        else: 
                            wrong += 1
                            c_perf[qc]["incorrect"] += 1
                            
                    net = (correct * 2) - (wrong * 0.66 if neg_mark else 0)
                    
                    test_count = len([x for x in st.session_state['quiz_history_log'] if x.get('subject') == sub_input]) + 1
                    test_name_formatted = f"{sub_input}_Test_{test_count}"
                    
                    st.session_state['quiz_history_log'].append({
                        "subject": sub_input,
                        "test_name": test_name_formatted,
                        "date_str": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
                        "correct": correct, "incorrect": wrong, "skipped": skipped,
                        "net": round(net, 2), "total_items": len(st.session_state['active_quiz']),
                        "penalty": round((wrong * 0.66 if neg_mark else 0), 2),
                        "chapter_perf": c_perf
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
                st.download_button("📄 Export Practice Set", data=md_out, file_name=f"Practice_{sub_input}.md", mime="text/markdown")
                
                st.write("---")
                for i, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Q{i+1}:** {q['question']}")
                    for k, v in q['options'].items():
                        if k == q['correct']: st.markdown(f"🟩 **{k}) {v} (Correct Key)**")
                        elif ans[i].startswith(k) and ans[i] != "Skip": st.markdown(f"🟥 **{k}) {v} (Your Pick)**")
                        else: st.markdown(f"⚪ {k}) {v}")
                    with st.expander("👁️ Core Conceptual Breakdown"):
                        st.write(f"**Explanation:** {q['explanation']}")
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
            st.subheader("Total Preparation Overview")
            df = pd.DataFrame(st.session_state['quiz_history_log'])
            if not df.empty:
                st.write(f"**Total Tests Taken:** {len(df)}")
                st.write(f"**Average Net Score:** {df['net'].mean():.2f}")
            
        for i, sub in enumerate(subjects):
            with tabs[i+1]:
                logs = [l for l in st.session_state['quiz_history_log'] if l.get('subject') == sub]
                if not logs: st.write("No tests recorded yet.")
                else:
                    for log in reversed(logs):
                        date_display = log.get('date_str', 'Unknown Date')
                        with st.expander(f"📋 {log.get('test_name', 'Test')} - {date_display}", expanded=False):
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

                            with cB:
                                ch_df = pd.DataFrame({"Outcome": ["Correct", "Wrong", "Skipped"], "Count": [log.get('correct',0), log.get('incorrect',0), log.get('skipped',0)]})
                                fig = px.pie(ch_df, values='Count', names='Outcome', color='Outcome', color_discrete_map={"Correct": "green", "Wrong": "red", "Skipped": "gray"})
                                fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
                                st.plotly_chart(fig, use_container_width=True)

with tab_history:
    st.header("🗄️ Master Question Repository")
    if st.session_state['old_questions']:
        # FEATURE 2: Organized Categorical Question Bank
        subjects_in_bank = list(set([q.get('subject', 'General') for q in st.session_state['old_questions']]))
        qb_tabs = st.tabs(subjects_in_bank)
        
        for idx, s_tab in enumerate(subjects_in_bank):
            with qb_tabs[idx]:
                sub_qs = [q for q in st.session_state['old_questions'] if q.get('subject') == s_tab]
                chapters_in_sub = list(set([q.get('chapter', 'General Review') for q in sub_qs]))
                
                st.write(f"**Total Questions Saved for {s_tab}: {len(sub_qs)}**")
                st.write("---")
                
                for chap in sorted(chapters_in_sub):
                    chap_qs = [q for q in sub_qs if q.get('chapter', 'General Review') == chap]
                    with st.expander(f"📖 Chapter: {chap} ({len(chap_qs)} questions)"):
                        for item in reversed(chap_qs):
                            # Displays the exact test number this question originated from
                            test_lbl = item.get('test_ref', 'Imported/Revision')
                            st.markdown(f"**[{test_lbl}]** {item['question']}")
                            for k, v in item['options'].items():
                                mark = "🟩" if k == item['correct'] else "⚪"
                                st.write(f"{mark} {k}) {v}")
                            st.write(f"**Explanation:** {item['explanation']}")
                            st.write("---")
    else:
        st.write("Storage registers empty.")

with tab_settings:
    st.header("⚙️ Database Backup & Restore")
    st.warning("If you are hosting this app on a free cloud server (like Streamlit Community Cloud), your data will eventually be wiped when the server sleeps. Use the buttons below to download your database to your PC/iPad, and upload it to restore your progress if it ever disappears.")
    
    col_dl, col_ul = st.columns(2)
    with col_dl:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r") as f: json_data = f.read()
            st.download_button(label="📥 Download Database Backup", data=json_data, file_name=f"BPSC_Backup_{datetime.datetime.now().strftime('%Y-%m-%d')}.json", mime="application/json", type="primary")
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
                    save_data()
                    st.success("Database restored successfully! The app will now refresh.")
                    time.sleep(2)
                    st.rerun()
                except Exception:
                    st.error("Invalid backup file.")
