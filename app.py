import streamlit as st
import PyPDF2
import google.generativeai as genai
import json
import random

# --- PAGE SETUP ---
st.set_page_config(page_title="BPSC Smart Quiz", page_icon="📚", layout="wide")

# --- INITIALIZE MEMORY BANKS ---
if 'current_chapters' not in st.session_state:
    st.session_state['current_chapters'] = []
if 'current_subject' not in st.session_state:
    st.session_state['current_subject'] = ""
if 'old_questions' not in st.session_state:
    st.session_state['old_questions'] = []
if 'active_quiz' not in st.session_state:
    st.session_state['active_quiz'] = None
if 'quiz_submitted' not in st.session_state:
    st.session_state['quiz_submitted'] = False

# --- API CONFIGURATION ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # Using gemini-1.5-flash for speed and structured outputs
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.warning("API Key not found or invalid. Please add GEMINI_API_KEY to your Streamlit Secrets.")

# --- HELPERS ---
def extract_index_text(pdf_file, num_pages=12):
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        pages_to_read = min(len(pdf_reader.pages), num_pages)
        for page_num in range(pages_to_read):
            text += pdf_reader.pages[page_num].extract_text() or ""
        return text
    except:
        return ""

def get_chapters_from_ai(text, subject_name):
    prompt = f"""
    Analyze this index text from a {subject_name} textbook. 
    Extract a clean list of individual chapter names.
    Return ONLY a valid JSON array of strings containing the chapter names. Do not include markdown blocks or any conversational text.
    Example output format: ["Chapter 1: Arrival of British", "Chapter 2: Revolt of 1857"]
    Text: {text}
    """
    try:
        response = model.generate_content(prompt)
        # Clean potential markdown wrapping if AI adds it
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except:
        return ["General Chapter 1", "General Chapter 2"]

def generate_new_questions(subject, chapter, difficulty, count):
    prompt = f"""
    You are an expert examiner for BPSC, UPSC, and Bihar state competitive exams.
    Generate exactly {count} distinct multiple-choice questions for:
    Subject: {subject}
    Chapter/Topic: {chapter}
    Difficulty Level: {difficulty}

    Strict Criteria:
    1. Tailor the standard to match real competitive exams (Easy=SSC CGL, Moderate=BPSC standard, Hard=UPSC Prelims/Tough BPSC, Very Hard=Deep conceptual analytical statements).
    2. Provide 4 options labeled A, B, C, D.
    3. Provide an absolute detailed explanation for the solution. Include a distinct 'Extra Value / PYQ Reference' point summarizing related concepts or factual trivia historically targeted in state exams.
    4. Return your output strictly as a JSON array matching this exact format:
    [
      {{
        "id": {random.randint(1000, 9999)},
        "question": "Question text here?",
        "options": {{"A": "Option A text", "B": "Option B text", "C": "Option C text", "D": "Option D text"}},
        "correct": "A",
        "explanation": "Detailed explanation text here.",
        "extra_info": "Extra historical trivia or PYQ context here."
      }}
    ]
    Do not wrap it in anything else except a clean JSON string.
    """
    try:
        response = model.generate_content(prompt)
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"Error generating questions: {e}")
        return []

# --- APP LAYOUT ---
st.title("📚 BPSC Smart Quiz Dashboard")
st.markdown("Your custom-tailored preparation engine designed for iPad & Desktop.")
st.write("---")

# Tab structure to split Setup and Revision
tab_quiz, tab_history = st.tabs(["🎯 Quiz Playground", "🗄️ Old Generated Questions (Revision)"])

with tab_quiz:
    col_setup, col_display = st.columns([1, 2])
    
    with col_setup:
        st.header("1. Sync Materials")
        sub_input = st.text_input("Subject Name:", value=st.session_state['current_subject'], placeholder="e.g., Indian Polity")
        uploaded_files = st.file_uploader("Upload Chapter/Book PDFs:", type="pdf", accept_multiple_files=True)
        
        if st.button("Extract Chapters"):
            if sub_input and uploaded_files:
                with st.spinner("Processing index data..."):
                    combined_chapters = []
                    for f in uploaded_files:
                        raw_index = extract_index_text(f)
                        chapters = get_chapters_from_ai(raw_index, sub_input)
                        combined_chapters.extend(chapters)
                    st.session_state['current_chapters'] = list(set(combined_chapters))
                    st.session_state['current_subject'] = sub_input
                    st.success(f"Loaded {len(st.session_state['current_chapters'])} chapters!")
            else:
                st.error("Please specify a Subject and upload at least one PDF.")
        
        st.write("---")
        st.header("2. Configure Quiz")
        
        # Chapter Selection Dropdown
        selected_ch = st.selectbox("Select Target Chapter:", options=st.session_state['current_chapters'] if st.session_state['current_chapters'] else ["Upload a file first"])
        
        # Difficulty & Volume
        diff_level = st.selectbox("Difficulty Level:", ["Easy", "Moderate", "Hard", "Very Hard"])
        q_count = st.slider("Number of Questions:", min_value=10, max_value=20, value=10)
        
        if st.button("Generate Mixed Quiz 🔥"):
            if not st.session_state['current_chapters']:
                st.error("Please upload materials and extract chapters first.")
            else:
                with st.spinner("Assembling custom quiz template..."):
                    # Pull relevant older questions for rotation mixing if available
                    matching_old = [q for q in st.session_state['old_questions'] if q['chapter'] == selected_ch]
                    
                    mix_old_count = min(len(matching_old), random.randint(2, 5)) if matching_old else 0
                    fresh_needed = q_count - mix_old_count
                    
                    # Fetch fresh questions from AI
                    fresh_qs = generate_new_questions(st.session_state['current_subject'], selected_ch, diff_level, fresh_needed)
                    
                    # Label fresh items with tracking details
                    for q in fresh_qs:
                        q['subject'] = st.session_state['current_subject']
                        q['chapter'] = selected_ch
                        q['difficulty'] = diff_level
                    
                    # Save fresh items permanently to the history storage bank
                    st.session_state['old_questions'].extend(fresh_qs)
                    
                    # Blend the active quiz pool
                    active_pool = fresh_qs
                    if mix_old_count > 0:
                        active_pool += random.sample(matching_old, mix_old_count)
                    random.shuffle(active_pool)
                    
                    st.session_state['active_quiz'] = active_pool
                    st.session_state['quiz_submitted'] = False
                    st.rerun()

    with col_display:
        st.header("3. Active Examination Session")
        
        if st.session_state['active_quiz']:
            st.info(f"📍 **Subject:** {st.session_state['current_subject']} | **Chapter:** {selected_ch}")
            
            user_answers = {}
            
            # Draw each question dynamically
            for idx, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"#### **Q{idx+1}. {q['question']}**")
                
                # Setup options layout
                opts = q['options']
                formatted_opts = [f"{k}) {v}" for k, v in opts.items()]
                
                # Checkbox selection
                user_sel = st.radio(
                    f"Choose your answer for Q{idx+1}:", 
                    options=["Not Answered"] + formatted_opts,
                    key=f"q_{q['id']}_{idx}",
                    label_visibility="collapsed"
                )
                user_answers[idx] = user_sel.split(")")[0] if ")" in user_sel else None
                st.write("")

            # Action Submission Bar
            if not st.session_state['quiz_submitted']:
                if st.button("Submit Answers Evaluation"):
                    st.session_state['quiz_submitted'] = True
                    st.rerun()
            else:
                st.success("Evaluation Report Generated below:")
                
                # Review Layout with Highlighting
                for idx, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Question {idx+1}:** {q['question']}")
                    
                    correct_key = q['correct']
                    user_key = user_answers[idx]
                    
                    # Custom styled display boxes for ipad compliance
                    for k, v in q['options'].items():
                        if k == correct_key:
                            st.markdown(f"🟩 **{k}) {v} (Correct Answer)**")
                        elif k == user_key and user_key != correct_key:
                            st.markdown(f"🟥 **{k}) {v} (Your Selection - Wrong)**")
                        else:
                            st.markdown(f"⚪ {k}) {v}")
                    
                    # Detailed Explanations
                    with st.expander("👁️ View Solutions & Extra Value Points"):
                        st.write(f"**Explanation:** {q['explanation']}")
                        st.markdown(f"💡 *Extra Value / PYQ Note:* {q['extra_info']}")
                
                if st.button("Clear and Start New Session"):
                    st.session_state['active_quiz'] = None
                    st.session_state['quiz_submitted'] = False
                    st.rerun()
        else:
            st.write("Configure settings in the left panel and click 'Generate Mixed Quiz' to begin.")

with tab_history:
    st.header("🗄️ Question History Vault")
    st.write(f"Total historical questions logged in session cache: **{len(st.session_state['old_questions'])}**")
    
    if st.session_state['old_questions']:
        for item in st.session_state['old_questions']:
            with st.expander(f"📚 [{item['subject']}] {item['chapter']} ({item['difficulty']}) - {item['question'][:60]}..."):
                st.markdown(f"**Full Question:** {item['question']}")
                for k, v in item['options'].items():
                    mark = "🟩" if k == item['correct'] else "⚪"
                    st.write(f"{mark} {k}) {v}")
                st.write(f"**Solution:** {item['explanation']}")
                st.info(f"PYQ Fact Check: {item['extra_info']}")
    else:
        st.write("No questions recorded yet. Newly generated questions will appear here automatically for permanent study reference.")
