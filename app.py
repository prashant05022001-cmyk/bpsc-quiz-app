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

# --- PAGE SETUP ---
st.set_page_config(page_title="Civil Services Smart Quiz Dashboard", page_icon="📚", layout="wide")

# --- INITIALIZE COGNITIVE DATA DEKS ---
# The vault now stores BOTH chapters and the extracted raw text content of the PDFs
if 'vault' not in st.session_state:
    st.session_state['vault'] = {
        "History": {"chapters": ["Revolt of 1857", "Socio-Religious Reform Movements", "Advent of Europeans", "Indian National Congress"], "content": ""},
        "Polity": {"chapters": ["Fundamental Rights", "Preamble & Historical Background", "Directive Principles of State Policy"], "content": ""},
        "Economics": {"chapters": ["National Income Accounting", "Inflation & Monetary Policy", "Budgeting and Fiscal Policy"], "content": ""}
    }
if 'old_questions' not in st.session_state:
    st.session_state['old_questions'] = []
if 'active_quiz' not in st.session_state:
    st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state:
    st.session_state['quiz_submitted'] = False
if 'quiz_history_log' not in st.session_state:
    st.session_state['quiz_history_log'] = [] 

# --- API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- SPEED OPTIMIZATION & EXTRACTION ---
@st.cache_data(show_spinner=False)
def extract_index_text(file_bytes, num_pages=30):
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        pages_to_read = min(len(pdf_reader.pages), num_pages)
        for page_num in range(pages_to_read):
            page_text = pdf_reader.pages[page_num].extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        return ""

def get_chapters_from_ai(text, subject_name):
    prompt = f"""
    Analyze this text from a {subject_name} textbook/index compilation. Extract the core chapter or topic names.
    Return ONLY a JSON array of strings. Example: ["Topic Alpha", "Topic Beta"]
    Text: {text}
    """
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except Exception as e:
        return []

def generate_new_questions(subject, chapters, difficulty, count, item_types, context_text):
    chapters_str = ", ".join(chapters)
    types_str = ", ".join(item_types)
    
    # We pass the saved PDF content to ground the AI's knowledge
    content_injection = f"Use this source material if relevant: {context_text[:25000]}" if context_text else ""
    
    prompt = f"""
    You are an elite expert examiner setting high-tier Civil Services competitive examinations. 
    Generate exactly {count} highly rigorous multiple-choice questions spanning these combined topics: {chapters_str} within the Subject: {subject}.
    Target Difficulty: {difficulty}. Balance the formats across: {types_str}.
    {content_injection}
    
    Return a clean JSON array matching this exact schema:
    [
      {{
        "id": {random.randint(10000, 99999)},
        "type": "Statement Based / MCQ / etc",
        "chapter": "Specific Chapter Name from the list",
        "question": "The comprehensive text of the question here including statement sets if any.",
        "options": {{"A": "Option Alpha", "B": "Option Beta", "C": "Option Gamma", "D": "Option Delta"}},
        "correct": "A",
        "explanation": "In-depth background analysis clarifying facts.",
        "extra_info": "High-value analytical observation or core conceptual point."
      }}
    ]
    """
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except Exception as e:
        st.error(f"🚨 AI Error Details: {str(e)}")
        return []

def generate_ai_insights(log_data):
    prompt = f"""
    Analyze this student's test performance: {log_data}.
    Write a short, highly analytical 2-paragraph strategy recommending how they can improve their weak areas and accelerate learning. Keep it professional.
    """
    try:
        return model.generate_content(prompt).text
    except:
        return "Insight generation temporarily unavailable."

def build_markdown_export(quiz_pool, subject):
    md = f"# Civil Services Exam Practice Set: {subject}\n\n"
    for idx, q in enumerate(quiz_pool):
        md += f"### Q{idx+1} [{q.get('type', 'MCQ')}] ({q.get('chapter', '')})\n"
        md += f"{q['question']}\n\n"
        for k, v in q['options'].items():
            md += f"- **{k}**: {v}\n"
        md += f"\n**Correct Answer:** Option {q['correct']}\n\n"
        md += f"**Explanation:** {q['explanation']}\n\n"
        md += f"**Key Value Point:** *{q['extra_info']}*\n"
        md += "---\n\n"
    return md

# --- APP LAYOUT ---
st.title("📚 Civil Services Custom Examination Hub")
st.markdown("Advanced analytical evaluation dashboard engineered for high-level preparation environments.")
st.write("---")

tab_quiz, tab_analytics, tab_history = st.tabs(["🎯 Live Test Simulation", "📊 Performance Analytics Dashboard", "🗄️ Question History Repository"])

with tab_quiz:
    col_setup, col_display = st.columns([1, 2])
    
    with col_setup:
        st.header("1. Sync Content Vault")
        
        existing_subjects = list(st.session_state['vault'].keys())
        subject_mode = st.radio("Subject Input:", ["Select Existing Subject", "Create New Subject"])
        
        if subject_mode == "Select Existing Subject" and existing_subjects:
            sub_input = st.selectbox("Choose Target Subject:", options=existing_subjects)
        else:
            sub_input = st.text_input("Enter New Subject Name:", placeholder="e.g., Geography")
            if sub_input and sub_input not in st.session_state['vault']:
                st.session_state['vault'][sub_input] = {"chapters": [], "content": ""}
        
        st.write("---")
        st.subheader("Add Content to Vault")
        opt_tab1, opt_tab2 = st.tabs(["📄 Upload & Save PDFs", "✍️ Manual Index Entry"])
        
        with opt_tab1:
            uploaded_files = st.file_uploader("Upload PDFs (Saved permanently to vault):", type="pdf", accept_multiple_files=True)
            if st.button("Extract & Save to Vault"):
                if sub_input and uploaded_files:
                    with st.spinner("Decoding and permanently storing content..."):
                        for f in uploaded_files:
                            raw_text = extract_index_text(f.getvalue())
                            extracted_chaps = get_chapters_from_ai(raw_text, sub_input)
                            
                            if extracted_chaps:
                                current_chaps = st.session_state['vault'][sub_input]["chapters"]
                                st.session_state['vault'][sub_input]["chapters"] = list(set(current_chaps + extracted_chaps))
                            
                            # Append the raw text to the subject's vault content so the AI can read it later!
                            st.session_state['vault'][sub_input]["content"] += "\n" + raw_text
                            
                        st.success(f"Chapters and PDF Content safely stored in '{sub_input}' vault!")
                        st.rerun()
                else:
                    st.error("Ensure Subject Name is established and files are queued.")
                    
        with opt_tab2:
            manual_chapters = st.text_area("Paste topics (one entry per line):", placeholder="e.g., Physiographic Divisions of India\nDrainage System")
            if st.button("Commit Topics"):
                if sub_input and manual_chapters:
                    new_chaps = [line.strip() for line in manual_chapters.split('\n') if line.strip()]
                    current_chaps = st.session_state['vault'][sub_input]["chapters"]
                    st.session_state['vault'][sub_input]["chapters"] = list(set(current_chaps + new_chaps))
                    st.success(f"Added {len(new_chaps)} chapters to {sub_input}!")
                    st.rerun()

        st.write("---")
        st.header("2. Build Custom Test Deck")
        
        available_chaps = st.session_state['vault'].get(sub_input, {}).get("chapters", []) if sub_input else []
        selected_ch_list = st.multiselect("Target Chapters (Select Multiple):", options=available_chaps)
        
        diff_level = st.selectbox("Target Analytical Rigor:", ["Easy Overview", "Moderate Conceptual", "Hard Applied", "Very Hard (UPSC/BPSC Rank Decider)"])
        q_count = st.slider("Target Question Volume:", min_value=5, max_value=25, value=10)
        
        st.markdown("**Session Constraints:**")
        time_limit_mins = st.number_input("Set Timer Duration (Minutes):", min_value=1, max_value=180, value=q_count)
        neg_marking_toggle = st.checkbox("Apply Standard Negative Marking (1/3rd penalty)", value=True)
        
        st.markdown("**Include Question Formats:**")
        mcq_type = st.checkbox("Single Correct MCQ", value=True)
        stmt_type = st.checkbox("Statement Based Questions", value=True)
        ar_type = st.checkbox("Assertion Reason Matrices", value=True)
        
        selected_patterns = []
        if mcq_type: selected_patterns.append("Single Correct MCQ")
        if stmt_type: selected_patterns.append("Statement Based Questions")
        if ar_type: selected_patterns.append("Assertion Reason")
        if not selected_patterns: selected_patterns.append("Single Correct MCQ")

        if st.button("Generate Mixed Deck (Old + New) 🔥"):
            if not selected_ch_list:
                st.error("Select at least one targeted chapter structure to execute compilation.")
            else:
                with st.spinner("Mixing existing knowledge base with freshly generated questions..."):
                    # 1. Fetch older questions for these chapters
                    matching_old = [q for q in st.session_state['old_questions'] if q['chapter'] in selected_ch_list and q['subject'] == sub_input]
                    
                    # 2. Determine ratio: Up to 1/3rd of the quiz can be old revision questions
                    mix_old_count = min(len(matching_old), max(1, q_count // 3)) if matching_old else 0
                    fresh_needed = q_count - mix_old_count
                    
                    vault_content = st.session_state['vault'].get(sub_input, {}).get("content", "")
                    
                    # 3. Generate the fresh batch
                    fresh_qs = generate_new_questions(sub_input, selected_ch_list, diff_level, fresh_needed, selected_patterns, vault_content)
                    
                    if fresh_qs or mix_old_count > 0:
                        for q in fresh_qs:
                            q['subject'] = sub_input
                            q['difficulty'] = diff_level
                        
                        st.session_state['old_questions'].extend(fresh_qs)
                        
                        active_pool = fresh_qs
                        if mix_old_count > 0:
                            active_pool += random.sample(matching_old, mix_old_count)
                        random.shuffle(active_pool)
                        
                        st.session_state['active_quiz'] = active_pool
                        st.session_state['quiz_submitted'] = False
                        st.session_state['test_start_time'] = time.time()
                        st.session_state['target_duration'] = time_limit_mins * 60 
                        st.rerun()
                    else:
                        st.error("AI Generation failed. Please try again.")

    with col_display:
        st.header("3. Examination Chamber")
        
        if st.session_state['active_quiz']:
            if not st.session_state['quiz_submitted']:
                elapsed = time.time() - st.session_state.get('test_start_time', time.time())
                remaining = max(0, int(st.session_state.get('target_duration', 600) - elapsed))
                mins, secs = divmod(remaining, 60)
                
                if remaining > 0:
                    st.metric(label="⏱️ Dynamic Session Countdown Time Remaining", value=f"{mins:02d}:{secs:02d}")
                    if st.button("Sync Timer / Refresh Board"):
                        st.rerun()
                else:
                    st.error("🚨 Allocated Session Duration Expired! Please compile your final responses immediately.")
            
            st.info(f"📍 **Active Evaluation Track:** {st.session_state['active_quiz'][0]['subject']}")
            
            user_answers = {}
            for idx, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"#### **Q{idx+1}. <span style='color:#007BFF;'>[{q.get('type', 'Analytical Evaluation')}]</span> {q['question']}**", unsafe_allow_html=True)
                opts = q['options']
                formatted_opts = [f"{k}) {v}" for k, v in opts.items()]
                
                user_sel = st.radio(
                    f"Selection Matrix Q{idx+1}:", 
                    options=["Not Attempted"] + formatted_opts,
                    key=f"live_q_{q['id']}_{idx}",
                    label_visibility="collapsed"
                )
                user_answers[idx] = user_sel.split(")")[0] if ")" in user_sel else "Not Attempted"
                st.write("")

            if not st.session_state['quiz_submitted']:
                if st.button("Submit Assessment & Close Papers"):
                    st.session_state['quiz_submitted'] = True
                    
                    correct_tally = 0
                    incorrect_tally = 0
                    skipped_tally = 0
                    chapter_perf = {ch: {"correct": 0, "incorrect": 0} for ch in selected_ch_list}
                    
                    for idx, q in enumerate(st.session_state['active_quiz']):
                        u_ans = user_answers[idx]
                        q_chap = q.get('chapter', 'Unknown')
                        if q_chap not in chapter_perf:
                            chapter_perf[q_chap] = {"correct": 0, "incorrect": 0}
                            
                        if u_ans == "Not Attempted":
                            skipped_tally += 1
                        elif u_ans == q['correct']:
                            correct_tally += 1
                            chapter_perf[q_chap]["correct"] += 1
                        else:
                            incorrect_tally += 1
                            chapter_perf[q_chap]["incorrect"] += 1
                            
                    raw_score = correct_tally * 2
                    penalty = (incorrect_tally * (2/3)) if neg_marking_toggle else 0.0
                    net_score = raw_score - penalty
                    
                    test_name = f"Mock Assessment #{len([log for log in st.session_state['quiz_history_log'] if log['subject'] == sub_input]) + 1}"
                    
                    st.session_state['quiz_history_log'].append({
                        "test_name": test_name,
                        "date_str": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
                        "subject": sub_input,
                        "correct": correct_tally,
                        "incorrect": incorrect_tally,
                        "skipped": skipped_tally,
                        "raw_score": raw_score,
                        "penalty": round(penalty, 2),
                        "net": round(net_score, 2),
                        "total_items": len(st.session_state['active_quiz']),
                        "chapter_perf": chapter_perf
                    })
                    st.rerun()
            else:
                st.success("📝 Performance Score Card Generated Successfully")
                latest_run = st.session_state['quiz_history_log'][-1]
                
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                m_col1.metric("Correct Selections", f"✅ {latest_run.get('correct', 0)}")
                m_col2.metric("Negative Penalties", f"❌ -{latest_run.get('penalty', 0)}")
                m_col3.metric("Skipped", f"⚪ {latest_run.get('skipped', 0)}")
                m_col4.metric("Net Secured Marks", f"🎯 {latest_run.get('net', 0.0)}")
                
                md_output = build_markdown_export(st.session_state['active_quiz'], st.session_state['active_quiz'][0]['subject'])
                st.download_button("📄 Export Practice Set & Solutions (.md format for iPad)", data=md_output, file_name=f"Exam_Practice_{st.session_state['active_quiz'][0]['subject']}.md", mime="text/markdown")
                
                st.write("---")
                for idx, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Question {idx+1}:** {q['question']}")
                    correct_key = q['correct']
                    user_key = user_answers[idx]
                    
                    for k, v in q['options'].items():
                        if k == correct_key:
                            st.markdown(f"🟩 **{k}) {v} (Accurate Key)**")
                        elif k == user_key and user_key != correct_key:
                            st.markdown(f"🟥 **{k}) {v} (Your Submission)**")
                        else:
                            st.markdown(f"⚪ {k}) {v}")
                    
                    with st.expander("👁️ View Core Conceptual Breakdown"):
                        st.write(f"**Explanation:** {q['explanation']}")
                        st.markdown(f"💡 *Strategic Point:* {q['extra_info']}")
                
                if st.button("Purge Current Deck & Reload Simulator"):
                    st.session_state['active_quiz'] = None
                    st.session_state['quiz_submitted'] = False
                    st.rerun()

with tab_analytics:
    st.header("📊 Performance Analytics Intelligence Dashboard")
    
    subjects = list(st.session_state['vault'].keys())
    
    if not st.session_state['quiz_history_log']:
        st.info("Performance dashboards will generate dynamically once you submit your first examination.")
    else:
        # Create dynamic tabs for every subject in the vault
        subject_tabs = st.tabs(subjects)
        
        for i, sub in enumerate(subjects):
            with subject_tabs[i]:
                sub_logs = [log for log in st.session_state['quiz_history_log'] if log['subject'] == sub]
                
                if not sub_logs:
                    st.write(f"No mock tests logged for {sub} yet.")
                else:
                    for log in reversed(sub_logs): # Show newest first
                        with st.expander(f"📋 {log['test_name']} - {log['date_str']}", expanded=True):
                            colA, colB = st.columns([1, 1])
                            
                            with colA:
                                st.markdown("### Score Matrix")
                                st.write(f"**Total Questions:** {log['total_items']}")
                                st.write(f"✅ **Right:** {log['correct']}")
                                st.write(f"❌ **Wrong:** {log['incorrect']}")
                                st.write(f"⚪ **Skipped:** {log['skipped']}")
                                st.markdown(f"#### 🎯 Net Marks: {log['net']} / {log['total_items']*2}")
                                st.markdown(f"⚠️ **Negative Marks Incurred:** -{log['penalty']}")
                                
                                # Chapter Strengths & Weaknesses
                                st.markdown("### Area Analysis")
                                chapter_perf = log.get('chapter_perf', {})
                                
                                best_chap = "N/A"
                                worst_chap = "N/A"
                                max_acc = -1
                                min_acc = 101
                                
                                for ch, metrics in chapter_perf.items():
                                    total_att = metrics['correct'] + metrics['incorrect']
                                    if total_att > 0:
                                        acc = (metrics['correct'] / total_att) * 100
                                        if acc > max_acc:
                                            max_acc = acc
                                            best_chap = ch
                                        if acc < min_acc:
                                            min_acc = acc
                                            worst_chap = ch
                                            
                                st.success(f"🌟 **Good Area:** {best_chap}")
                                st.error(f"📉 **Area of Improvement:** {worst_chap}")

                            with colB:
                                st.markdown("### Marks Distribution")
                                # Plotly Pie Chart
                                df = pd.DataFrame({
                                    "Outcome": ["Correct Selections", "Incorrect (Errors)", "Skipped"],
                                    "Count": [log['correct'], log['incorrect'], log['skipped']]
                                })
                                fig = px.pie(df, values='Count', names='Outcome', color='Outcome',
                                             color_discrete_map={"Correct Selections": "green", "Incorrect (Errors)": "red", "Skipped": "gray"})
                                fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
                                st.plotly_chart(fig, use_container_width=True)
                            
                            st.write("---")
                            if st.button(f"Generate AI Improvement Strategy for {log['test_name']}", key=f"btn_{log['test_name']}_{log['date_str']}"):
                                with st.spinner("AI analyzing your specific test errors..."):
                                    insights = generate_ai_insights(log)
                                    st.info(f"💡 **AI Growth Plan:**\n\n{insights}")

with tab_history:
    st.header("🗄️ Master Question Repository")
    st.write(f"Total entries securely logged: **{len(st.session_state['old_questions'])}**")
    
    if st.session_state['old_questions']:
        for item in st.session_state['old_questions']:
            with st.expander(f"📚 [{item['subject']}] - {item.get('chapter', 'General Review')} | {item['question'][:80]}..."):
                st.markdown(f"**Question:** {item['question']}")
                for k, v in item['options'].items():
                    mark = "🟩" if k == item['correct'] else "⚪"
                    st.write(f"{mark} {k}) {v}")
                st.write(f"**Explanation:** {item['explanation']}")
    else:
        st.write("Storage registers empty.")
