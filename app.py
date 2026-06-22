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
def extract_index_text(file_bytes, num_pages=50): 
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
            if "429" in str(e) or "Quota exceeded" in str(e):
                time.sleep(15)
            else:
                return []
    return []

def generate_new_questions(subject, chapters, difficulty, count, item_types, vault_full_text, retries=2):
    # SMART FILTER (TOKEN DIET) - Preserves quota while feeding AI the right data
    relevant_context = ""
    if vault_full_text:
        relevant_context = vault_full_text[:2000] 
        for ch in chapters:
            start_idx = vault_full_text.find(ch)
            if start_idx != -1:
                relevant_context += "\n... " + vault_full_text[max(0, start_idx-500) : start_idx+1500]
    relevant_context = relevant_context[:10000]

    prompt = f"""
    Elite Civil Services Examiner Mode.
    Generate {count} distinct questions for Subject: {subject} | Chapters: {', '.join(chapters)}.
    Difficulty: {difficulty}. Formats: {', '.join(item_types)}.
    Source Material context: {relevant_context}

    Return JSON array matching EXACTLY:
    [
      {{"id": {random.randint(1000,9999)}, "type": "MCQ", "chapter": "{chapters[0]}", "question": "Question text...", "options": {{"A": "Opt A", "B": "Opt B", "C": "Opt C", "D": "Opt D"}}, "correct": "A", "explanation": "Detailed explanation.", "extra_info": "Strategic Fact."}}
    ]
    """
    for attempt in range(retries):
        try:
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                st.warning(f"Speed limit hit. AI is pausing. Retrying in 20s... ({attempt+1}/2)")
                time.sleep(20)
            else:
                return []
    return []

def generate_ai_insights(log_data):
    try:
        return model.generate_content(f"Analyze this test performance and suggest a highly professional UPSC study strategy: {log_data}").text
    except:
        return "Insights unavailable at this time."

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

tab_quiz, tab_analytics, tab_history = st.tabs(["🎯 Live Simulator", "📊 Analytics Hub", "🗄️ Question Bank"])

with tab_quiz:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.header("1. Sync Content Vault")
        existing_subs = list(st.session_state['vault'].keys())
        sub_mode = st.radio("Mode:", ["Existing Subject", "New Subject"])
        if sub_mode == "Existing Subject" and existing_subs:
            sub_input = st.selectbox("Subject:", options=existing_subs)
        else:
            sub_input = st.text_input("New Subject:")
        
        if sub_input and sub_input not in st.session_state['vault']:
            st.session_state['vault'][sub_input] = {"chapters": [], "content": ""}
            save_data()

        st.write("---")
        opt1, opt2 = st.tabs(["📄 Upload PDF", "✍️ Manual"])
        with opt1:
            up_files = st.file_uploader("Upload Study Material (Saved Permanently)", type="pdf", accept_multiple_files=True)
            if st.button("Extract & Save to Vault"):
                if up_files and sub_input:
                    with st.spinner("Vaulting content safely..."):
                        for f in up_files:
                            t = extract_index_text(f.getvalue())
                            ch = get_chapters_from_ai(t, sub_input)
                            st.session_state['vault'][sub_input]["chapters"] = list(set(st.session_state['vault'][sub_input]["chapters"] + ch))
                            st.session_state['vault'][sub_input]["content"] += "\n" + t
                            time.sleep(4) # Speed bump
                        save_data()
                        st.success("Saved safely to your Hard Drive!")
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
        chaps = st.session_state['vault'].get(sub_input, {}).get("chapters", [])
        sel_chaps = st.multiselect("Select Topics:", options=chaps)
        diff = st.selectbox("Difficulty:", ["Moderate", "Hard", "UPSC Level"])
        q_vol = st.slider("Questions:", 5, 20, 10)
        t_limit = st.number_input("Timer (Mins):", 1, 60, q_vol)
        neg_mark = st.checkbox("Negative Marking (1/3rd)", True)
        
        if st.button("Generate Question Deck 🔥"):
            if sel_chaps:
                with st.spinner("Compiling questions using Smart Filter..."):
                    v_text = st.session_state['vault'][sub_input]["content"]
                    matching_old = [q for q in st.session_state['old_questions'] if q.get('chapter') in sel_chaps and q.get('subject') == sub_input]
                    mix_count = min(len(matching_old), max(1, q_vol // 3)) if matching_old else 0
                    fresh_needed = q_vol - mix_count
                    
                    qs = generate_new_questions(sub_input, sel_chaps, diff, fresh_needed, ["Single Correct MCQ", "Statement Based"], v_text)
                    if qs or mix_count > 0:
                        for q in qs:
                            q['subject'] = sub_input
                            q['difficulty'] = diff
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

    with col2:
        st.header("3. Examination Chamber")
        if st.session_state['active_quiz']:
            if not st.session_state['quiz_submitted']:
                rem = max(0, int(st.session_state.get('target_duration', 600) - (time.time() - st.session_state.get('test_start_time', time.time()))))
                st.metric("Time Remaining", f"{rem//60:02d}:{rem%60:02d}")
            
            ans = {}
            for i, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"**Q{i+1}.** <span style='color:#007BFF;'>[{q.get('type', 'MCQ')}]</span> {q['question']}", unsafe_allow_html=True)
                ans[i] = st.radio(f"Opt {i}", options=["Skip"] + [f"{k}) {v}" for k,v in q['options'].items()], key=f"q{i}", label_visibility="collapsed")
                st.write("")

            if not st.session_state['quiz_submitted']:
                if st.button("Submit Assessment & Evaluate"):
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
                    st.session_state['quiz_history_log'].append({
                        "subject": sub_input,
                        "test_name": f"Mock Test #{len([x for x in st.session_state['quiz_history_log'] if x.get('subject')==sub_input])+1}",
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
    if not st.session_state['quiz_history_log']:
        st.info("Performance dashboards will generate dynamically after your first test.")
    else:
        tabs = st.tabs(subjects)
        for i, sub in enumerate(subjects):
            with tabs[i]:
                logs = [l for l in st.session_state['quiz_history_log'] if l.get('subject') == sub]
                if not logs: st.write("No tests recorded yet.")
                else:
                    for log in reversed(logs):
                        # Safely retrieves date whether it's stored as date_str (new) or date (old) to prevent KeyError
                        date_display = log.get('date_str', log.get('date', 'Unknown Date'))
                        with st.expander(f"📋 {log.get('test_name', 'Test')} - {date_display}", expanded=True):
                            cA, cB = st.columns([1, 1])
                            with cA:
                                st.markdown("### Score Matrix")
                                st.write(f"**Total Questions:** {log.get('total_items', log.get('total',0))}")
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
                                df = pd.DataFrame({"Outcome": ["Correct", "Wrong", "Skipped"], "Count": [log.get('correct',0), log.get('incorrect',0), log.get('skipped',0)]})
                                fig = px.pie(df, values='Count', names='Outcome', color='Outcome', color_discrete_map={"Correct": "green", "Wrong": "red", "Skipped": "gray"})
                                fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
                                st.plotly_chart(fig, use_container_width=True)
                            
                            if st.button("Generate AI Strategy", key=f"ai_{log.get('test_name')}_{date_display}"):
                                with st.spinner("Analyzing..."):
                                    st.info(generate_ai_insights(log))

with tab_history:
    st.header("🗄️ Master Question Repository")
    st.write(f"Entries safely logged: **{len(st.session_state['old_questions'])}**")
    for item in reversed(st.session_state['old_questions']):
        with st.expander(f"📚 [{item.get('subject')}] - {item.get('chapter', 'General Review')} | {item['question'][:80]}..."):
            st.markdown(f"**Question:** {item['question']}")
            for k, v in item['options'].items():
                mark = "🟩" if k == item['correct'] else "⚪"
                st.write(f"{mark} {k}) {v}")
            st.write(f"**Explanation:** {item['explanation']}")
