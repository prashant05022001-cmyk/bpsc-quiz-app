import streamlit as st
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
        "vault": {
            "History": {"chapters": ["Revolt of 1857", "Socio-Religious Movements"], "content": ""},
            "Polity": {"chapters": ["Fundamental Rights", "Preamble"], "content": ""},
            "Economics": {"chapters": ["Inflation", "Budget"], "content": ""}
        },
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

if 'active_quiz' not in st.session_state:
    st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state:
    st.session_state['quiz_submitted'] = False

# --- API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- HELPERS ---
@st.cache_data(show_spinner=False)
def extract_index_text(file_bytes, num_pages=50): # Increased to 50 pages for better vaulting
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        pages_to_read = min(len(pdf_reader.pages), num_pages)
        for page_num in range(pages_to_read):
            page_text = pdf_reader.pages[page_num].extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception:
        return ""

def get_chapters_from_ai(text, subject_name, retries=2):
    prompt = f"Extract chapter names from this {subject_name} index. Return ONLY a JSON array of strings."
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt + f"\nText: {text[:10000]}", generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                time.sleep(15)
            else:
                return []
    return []

def generate_new_questions(subject, chapters, difficulty, count, item_types, vault_full_text, retries=2):
    # SMART FILTER: Instead of sending 25k chars, we find the paragraphs that mention our selected chapters
    relevant_context = ""
    if vault_full_text:
        # We look for the first 2000 characters and any sections containing the chapter name
        relevant_context = vault_full_text[:2000] 
        for ch in chapters:
            start_idx = vault_full_text.find(ch)
            if start_idx != -1:
                # Grab 2000 characters around the chapter name
                relevant_context += "\n... " + vault_full_text[max(0, start_idx-500) : start_idx+1500]
    
    # Final "Smart Diet" limit (10,000 chars is the sweet spot for Free Tier)
    relevant_context = relevant_context[:10000]

    prompt = f"""
    Elite Civil Services Examiner Mode.
    Generate {count} questions for Subject: {subject} | Chapters: {', '.join(chapters)}.
    Difficulty: {difficulty}. Formats: {', '.join(item_types)}.
    Source Material context: {relevant_context}

    Return JSON array:
    [
      {{"id": {random.randint(1000,9999)}, "type": "MCQ", "chapter": "Name", "question": "...", "options": {{"A": "..", "B": "..", "C": "..", "D": ".."}}, "correct": "A", "explanation": "...", "extra_info": "..."}}
    ]
    """
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e):
                st.warning(f"Speed limit hit. Retrying in 20s... ({attempt+1}/2)")
                time.sleep(20)
            else:
                return []
    return []

def generate_ai_insights(log_data):
    try:
        return model.generate_content(f"Analyze this test performance and suggest a UPSC study strategy: {log_data}").text
    except:
        return "Insights unavailable."

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

tab_quiz, tab_analytics, tab_history = st.tabs(["🎯 Quiz", "📊 Analytics", "🗄️ Repository"])

with tab_quiz:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.header("1. Vault")
        existing_subs = list(st.session_state['vault'].keys())
        sub_input = st.selectbox("Subject:", options=existing_subs) if existing_subs else st.text_input("New Subject:")
        
        if sub_input and sub_input not in st.session_state['vault']:
            st.session_state['vault'][sub_input] = {"chapters": [], "content": ""}
            save_data()

        up_files = st.file_uploader("Upload Study Material (PDF)", type="pdf", accept_multiple_files=True)
        if st.button("Save to Vault"):
            if up_files:
                with st.spinner("Vaulting..."):
                    for f in up_files:
                        t = extract_index_text(f.getvalue())
                        ch = get_chapters_from_ai(t, sub_input)
                        st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + ch))
                        st.session_state['vault'][sub_input]["content"] += "\n" + t
                        time.sleep(5)
                    save_data()
                    st.success("Saved!")
                    st.rerun()

        st.header("2. Build Test")
        chaps = st.session_state['vault'].get(sub_input, {}).get("chapters", [])
        sel_chaps = st.multiselect("Select Topics:", options=chaps)
        q_vol = st.slider("Questions:", 5, 20, 10)
        t_limit = st.number_input("Minutes:", 1, 60, q_vol)
        
        if st.button("Start Quiz 🔥"):
            if sel_chaps:
                with st.spinner("Generating..."):
                    v_text = st.session_state['vault'][sub_input]["content"]
                    qs = generate_new_questions(sub_input, sel_chaps, "Hard", q_vol, ["MCQ", "Statement Based"], v_text)
                    if qs:
                        st.session_state['old_questions'].extend(qs)
                        save_data()
                        st.session_state['active_quiz'] = qs
                        st.session_state['quiz_submitted'] = False
                        st.session_state['test_start_time'] = time.time()
                        st.session_state['target_duration'] = t_limit * 60
                        st.rerun()

    with col2:
        st.header("3. Exam Hall")
        if st.session_state['active_quiz']:
            if not st.session_state['quiz_submitted']:
                rem = max(0, int(st.session_state.get('target_duration', 600) - (time.time() - st.session_state.get('test_start_time', time.time()))))
                st.metric("Time Remaining", f"{rem//60:02d}:{rem%60:02d}")
            
            ans = {}
            for i, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"**Q{i+1}.** {q['question']}")
                ans[i] = st.radio(f"Opt {i}", options=["Skip"] + [f"{k}) {v}" for k,v in q['options'].items()], key=f"q{i}", label_visibility="collapsed")

            if st.button("Submit Assessment"):
                st.session_state['quiz_submitted'] = True
                correct = sum(1 for i, q in enumerate(st.session_state['active_quiz']) if ans[i].startswith(q['correct']))
                wrong = len(st.session_state['active_quiz']) - correct - sum(1 for i in ans if ans[i] == "Skip")
                net = (correct * 2) - (wrong * 0.66)
                st.session_state['quiz_history_log'].append({"subject": sub_input, "test_name": f"Test {len(st.session_state['quiz_history_log'])+1}", "date": datetime.datetime.now().strftime("%d %b"), "correct": correct, "incorrect": wrong, "net": round(net, 2), "total": len(st.session_state['active_quiz'])})
                save_data()
                st.rerun()
            
            if st.session_state['quiz_submitted']:
                st.success(f"Score: {st.session_state['quiz_history_log'][-1]['net']}")
                if st.button("New Test"):
                    st.session_state['active_quiz'] = None
                    st.rerun()

with tab_analytics:
    if st.session_state['quiz_history_log']:
        df = pd.DataFrame(st.session_state['quiz_history_log'])
        for sub in df['subject'].unique():
            st.subheader(f"Subject: {sub}")
            sub_df = df[df['subject'] == sub]
            st.table(sub_df[['test_name', 'date', 'correct', 'incorrect', 'net']])
            fig = px.pie(values=[sub_df['correct'].sum(), sub_df['incorrect'].sum()], names=['Correct', 'Wrong'], color_discrete_sequence=['green', 'red'])
            st.plotly_chart(fig)
    else: st.info("No data yet.")

with tab_history:
    for q in reversed(st.session_state['old_questions']):
        with st.expander(f"[{q.get('subject')}] {q['question'][:50]}..."):
            st.write(q['question'])
            st.write(f"Correct: {q['correct']} | Expl: {q['explanation']}")
