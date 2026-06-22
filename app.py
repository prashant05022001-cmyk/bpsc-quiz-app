import streamlit as st
import PyPDF2
import google.generativeai as genai
import json
import random
import time

# --- PAGE SETUP ---
st.set_page_config(page_title="Civil Services Smart Quiz Dashboard", page_icon="📚", layout="wide")

# --- INITIALIZE COGNITIVE DATA DEKS (PERSISTENT ALONG SESSION) ---
if 'vault' not in st.session_state:
    # Pre-populating structure for persistent tracking
    st.session_state['vault'] = {
        "History": ["Revolt of 1857", "Socio-Religious Reform Movements", "Advent of Europeans", "Indian National Congress"],
        "Polity": ["Fundamental Rights", "Preamble & Historical Background", "Directive Principles of State Policy"],
        "Economics": ["National Income Accounting", "Inflation & Monetary Policy", "Budgeting and Fiscal Policy"]
    }
if 'old_questions' not in st.session_state:
    st.session_state['old_questions'] = []
if 'active_quiz' not in st.session_state:
    st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state:
    st.session_state['quiz_submitted'] = False
if 'quiz_history_log' not in st.session_state:
    st.session_state['quiz_history_log'] = [] # Stores performance metrics

# --- API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- HELPERS ---
def extract_index_text(pdf_file, num_pages=20):
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
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
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        return []

def generate_new_questions(subject, chapters, difficulty, count, item_types):
    chapters_str = ", ".join(chapters)
    types_str = ", ".join(item_types)
    
    prompt = f"""
    You are an elite expert examiner setting high-tier Civil Services competitive examinations. 
    Generate exactly {count} highly rigorous multiple-choice questions spanning these combined topics: {chapters_str} within the Subject: {subject}.
    Target Difficulty: {difficulty}
    
    You must balance the selection across the following requested question formats: {types_str}.
    
    CRITICAL FORMAT STIPULATIONS FOR PATTERNS:
    1. Single Correct MCQ: Standard four-option analytical questions.
    2. Statement Based Questions: Provide 2 or 3 numbered statements, followed by standard choices (e.g., "Only 1 and 2", "All of the above").
    3. Assertion Reason: Formatted strictly with an 'Assertion (A)' and 'Reason (R)' text followed by analytical correlation evaluations.
    4. Match the Following: Formatted with List I and List II pairs, with the options showing the accurate alphanumeric mapping combinations.
    5. Chronology Based: Present historical developments/events/phases to be re-arranged into accurate sequential progression timelines.
    6. Map Based / Spatial Context: Frame situational questions evaluating spatial distribution, geographical markers, or structural setups described conceptually.
    7. Multiple Statement Analysis: Multi-layered evaluation parameters assessing truth thresholds of institutional actions or systemic conditions.

    Return a clean JSON array matching this exact schema:
    [
      {{
        "id": {random.randint(10000, 99999)},
        "type": "Statement Based / Assertion Reason / etc",
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
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"🚨 Google AI Error Details: {str(e)}")
        return []

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

tab_quiz, tab_analytics, tab_history = st.tabs(["🎯 Live Test Simulation", "📊 Performance Analytics", "🗄️ Question History Repository"])

with tab_quiz:
    col_setup, col_display = st.columns([1, 2])
    
    with col_setup:
        st.header("1. Sync Content Vault")
        
        # Subject selection linked directly to persistence engine
        existing_subjects = list(st.session_state['vault'].keys())
        subject_mode = st.radio("Subject Input:", ["Select Existing Subject", "Create New Subject"])
        
        if subject_mode == "Select Existing Subject" and existing_subjects:
            sub_input = st.selectbox("Choose Target Subject:", options=existing_subjects)
        else:
            sub_input = st.text_input("Enter New Subject Name:", placeholder="e.g., Geography")
            if sub_input and sub_input not in st.session_state['vault']:
                st.session_state['vault'][sub_input] = []
        
        st.write("---")
        st.subheader("Add Topics to Subject")
        opt_tab1, opt_tab2 = st.tabs(["📄 Automated PDF Scan", "✍️ Manual Index Entry"])
        
        with opt_tab1:
            uploaded_files = st.file_uploader("Upload Compilation/Index PDFs:", type="pdf", accept_multiple_files=True)
            if st.button("Extract via Gemini 2.5 Engine"):
                if sub_input and uploaded_files:
                    with st.spinner("Decoding content index matrices..."):
                        for f in uploaded_files:
                            raw_index = extract_index_text(f)
                            extracted = get_chapters_from_ai(raw_index, sub_input)
                            if extracted:
                                updated_list = list(set(st.session_state['vault'].get(sub_input, []) + extracted))
                                st.session_state['vault'][sub_input] = updated_list
                        st.success(f"Successfully integrated chapters into database.")
                        st.rerun()
                else:
                    st.error("Ensure Subject Name is established and files are queued.")
                    
        with opt_tab2:
            manual_chapters = st.text_area("Paste topics (one entry per line):", placeholder="e.g., Physiographic Divisions of India\nDrainage System")
            if st.button("Commit Topics"):
                if sub_input and manual_chapters:
                    new_chaps = [line.strip() for line in manual_chapters.split('\n') if line.strip()]
                    st.session_state['vault'][sub_input] = list(set(st.session_state['vault'].get(sub_input, []) + new_chaps))
                    st.success(f"Added {len(new_chaps)} chapters to {sub_input}!")
                    st.rerun()

        st.write("---")
        st.header("2. Build Custom Test Deck")
        
        available_chaps = st.session_state['vault'].get(sub_input, []) if sub_input else []
        
        # MULTI-CHAPTER SELECTION COMPONENT
        selected_ch_list = st.multiselect("Target Chapters (Select Multiple):", options=available_chaps)
        
        diff_level = st.selectbox("Target Analytical Rigor:", ["Easy Overview", "Moderate Conceptual", "Hard Applied", "Very Hard (UPSC/BPSC Rank Decider)"])
        q_count = st.slider("Target Question Volume:", min_value=5, max_value=25, value=10)
        
        # NEGATIVE MARKING CONTROLS
        neg_marking_toggle = st.checkbox("Apply Standard Negative Marking (1/3rd penalty)", value=True)
        
        # ADVANCED COMPETITIVE EXAMINATION PATTERNS SELECTION
        st.markdown("**Include Question Formats:**")
        mcq_type = st.checkbox("Single Correct MCQ", value=True)
        stmt_type = st.checkbox("Statement Based Questions", value=True)
        ar_type = st.checkbox("Assertion Reason Matrices", value=True)
        match_type = st.checkbox("Match the Following", value=True)
        chrono_type = st.checkbox("Chronology Sequences", value=True)
        map_type = st.checkbox("Map/Spatial Contextualized", value=True)
        multi_stmt_type = st.checkbox("Multiple Statement Analysis", value=True)
        
        selected_patterns = []
        if mcq_type: selected_patterns.append("Single Correct MCQ")
        if stmt_type: selected_patterns.append("Statement Based Questions")
        if ar_type: selected_patterns.append("Assertion Reason")
        if match_type: selected_patterns.append("Match the Following")
        if chrono_type: selected_patterns.append("Chronology Based")
        if map_type: selected_patterns.append("Map Based")
        if multi_stmt_type: selected_patterns.append("Multiple Statement Analysis")

        if st.button("Generate Balanced Question Deck 🔥"):
            if not selected_ch_list:
                st.error("Select at least one targeted chapter structure to execute compilation.")
            elif not selected_patterns:
                st.error("Select at least one question format pattern.")
            else:
                with st.spinner("Compiling multi-pattern question structure from engine servers..."):
                    fresh_qs = generate_new_questions(sub_input, selected_ch_list, diff_level, q_count, selected_patterns)
                    if fresh_qs:
                        for q in fresh_qs:
                            q['subject'] = sub_input
                            q['difficulty'] = diff_level
                        st.session_state['old_questions'].extend(fresh_qs)
                        st.session_state['active_quiz'] = fresh_qs
                        st.session_state['quiz_submitted'] = False
                        st.session_state['test_start_time'] = time.time()
                        st.session_state['target_duration'] = q_count * 60 # Allocating 1 minute per item
                        st.rerun()

    with col_display:
        st.header("3. Examination Chamber")
        
        if st.session_state['active_quiz']:
            # DYNAMIC LIVE EXAM COUNTDOWN TIMER COMPONENT
            if not st.session_state['quiz_submitted']:
                elapsed = time.time() - st.session_state.get('test_start_time', time.time())
                remaining = max(0, int(st.session_state.get('target_duration', 600) - elapsed))
                mins, secs = divmod(remaining, 60)
                
                if remaining > 0:
                    st.metric(label="⏱️ Dynamic Session Countdown Time Remaining", value=f"{mins:02d}:{secs:02d}")
                    if st.button("Force Sync Timer / Refresh Board View"):
                        st.rerun()
                else:
                    st.error("🚨 Allocated Session Duration Expired! Please compile your final responses immediately.")
            
            st.info(f"📍 **Active Evaluation Track:** {st.session_state['active_quiz'][0]['subject']} | Chapters: {', '.join(list(set([q.get('chapter','') for q in st.session_state['active_quiz']])))}")
            
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
                    
                    # Compute Performance Score Metrics
                    correct_tally = 0
                    incorrect_tally = 0
                    skipped_tally = 0
                    
                    for idx, q in enumerate(st.session_state['active_quiz']):
                        u_ans = user_answers[idx]
                        if u_ans == "Not Attempted":
                            skipped_tally += 1
                        elif u_ans == q['correct']:
                            correct_tally += 1
                        else:
                            incorrect_tally += 1
                            
                    # Raw and Net Evaluation Calculation (Applying 1/3 penalty factor)
                    raw_score = correct_tally * 2 # Assumed 2 marks per question typical setup
                    penalty = (incorrect_tally * (2/3)) if neg_marking_toggle else 0.0
                    net_score = raw_score - penalty
                    
                    # Store Metrics data point permanently for analysis
                    st.session_state['quiz_history_log'].append({
                        "subject": q['subject'],
                        "correct": correct_tally,
                        "incorrect": incorrect_tally,
                        "skipped": skipped_tally,
                        "net": round(net_score, 2),
                        "total_items": len(st.session_state['active_quiz'])
                    })
                    st.rerun()
            else:
                # Post-Submission Evaluation Matrix Display
                st.success("📝 Performance Score Card Generated Successfully")
                latest_run = st.session_state['quiz_history_log'][-1] if st.session_state['quiz_history_log'] else {}
                
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                m_col1.metric("Correct Selections", f"✅ {latest_run.get('correct', 0)}")
                m_col2.metric("Inaccurate Penalties", f"❌ {latest_run.get('incorrect', 0)}")
                m_col3.metric("Skipped", f"⚪ {latest_run.get('skipped', 0)}")
                m_col4.metric("Net Secured Marks", f"🎯 {latest_run.get('net', 0.0)}")
                
                # ONE-CLICK EXPORT TO MARKDOWN / DETAILED TEXT BLOCK DOWNLOAD COMPONENT
                md_output = build_markdown_export(st.session_state['active_quiz'], st.session_state['active_quiz'][0]['subject'])
                st.download_button(
                    label="📄 Export Practice Set & Solutions (.md format for iPad)",
                    data=md_output,
                    file_name=f"Exam_Practice_{st.session_state['active_quiz'][0]['subject']}.md",
                    mime="text/markdown"
                )
                
                st.write("---")
                st.subheader("Granular Question Verification View")
                for idx, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Question {idx+1}:** {q['question']}")
                    correct_key = q['correct']
                    user_key = user_answers[idx]
                    
                    for k, v in q['options'].items():
                        if k == correct_key:
                            st.markdown(f"🟩 **{k}) {v} (Accurate Key)**")
                        elif k == user_key and user_key != correct_key:
                            st.markdown(f"🟥 **{k}) {v} (Your Operational Submission)**")
                        else:
                            st.markdown(f"⚪ {k}) {v}")
                    
                    with st.expander("👁️ Core Analysis & High-Value Conceptual Check"):
                        st.write(f"**Detailed Breakdown:** {q['explanation']}")
                        st.markdown(f"💡 *Strategic Point:* {q['extra_info']}")
                
                if st.button("Purge Current Deck & Reload Simulator"):
                    st.session_state['active_quiz'] = None
                    st.session_state['quiz_submitted'] = False
                    st.rerun()
        else:
            st.write("Establish setup metrics on the control panel to generate your strategic test series compilation.")

with tab_analytics:
    st.header("📊 Performance Analytics Intelligence Dashboard")
    if st.session_state['quiz_history_log']:
        # Extract and aggregate dynamic analysis points
        total_tests = len(st.session_state['quiz_history_log'])
        accumulated_correct = sum(item['correct'] for item in st.session_state['quiz_history_log'])
        accumulated_incorrect = sum(item['incorrect'] for item in st.session_state['quiz_history_log'])
        accumulated_items = sum(item['total_items'] for item in st.session_state['quiz_history_log'])
        
        overall_accuracy = (accumulated_correct / accumulated_items) * 100 if accumulated_items > 0 else 0.0
        
        an_col1, an_col2, an_col3 = st.columns(3)
        an_col1.metric("Total Practice Sets Taken", f"📝 {total_tests}")
        an_col2.metric("Cumulative Accuracy Quotient", f"{overall_accuracy:.2f}%")
        an_col3.metric("Net Negative Errors Logged", f"⚠️ {accumulated_incorrect} items")
        
        st.write("---")
        st.subheader("Subject-Wise Accuracy Trends")
        
        # Build lightweight internal aggregation matrix
        subject_stats = {}
        for item in st.session_state['quiz_history_log']:
            sub = item['subject']
            if sub not in subject_stats:
                subject_stats[sub] = {"correct": 0, "total": 0}
            subject_stats[sub]["correct"] += item['correct']
            subject_stats[sub]["total"] += item['total_items']
            
        chart_data = {}
        for sub, data in subject_stats.items():
            accuracy = (data["correct"] / data["total"]) * 100 if data["total"] > 0 else 0.0
            chart_data[sub] = accuracy
            
        st.bar_chart(chart_data)
        
        # Display warning indicators for chapters needing revision
        st.markdown("### ⚠️ Targeted Revision Advisory Metrics")
        for sub, data in subject_stats.items():
            accuracy = (data["correct"] / data["total"]) * 100 if data["total"] > 0 else 0.0
            if accuracy < 65.0:
                st.warning(f"🚨 **Critical Alert in {sub}:** Average score sits at {accuracy:.1f}%. High negative error rates detected. Review historical compilation material immediately.")
            else:
                st.success(f"📈 **Optimal Mastery in {sub}:** Scoring strong at {accuracy:.1f}%. Retain current momentum.")
    else:
        st.info("Performance dashboards generate dynamically as evaluation sets are finalized.")

with tab_history:
    st.header("🗄️ Question History Repository")
    st.write(f"Total entries logged in master storage structure: **{len(st.session_state['old_questions'])}**")
    
    if st.session_state['old_questions']:
        for item in st.session_state['old_questions']:
            with st.expander(f"📚 [{item['subject']}] - Formula: {item.get('type','Standard MCQ')} | {item.get('chapter', 'General Review')} - {item['question'][:80]}..."):
                st.markdown(f"**Question Structure:** {item['question']}")
                for k, v in item['options'].items():
                    mark = "🟩" if k == item['correct'] else "⚪"
                    st.write(f"{mark} {k}) {v}")
                st.write(f"**Official Key Analytical Explanation:** {item['explanation']}")
                st.info(f"Strategic Point: {item['extra_info']}")
    else:
        st.write("Storage registers empty.")
