import streamlit as st
import PyPDF2
import google.generativeai as genai
import json
import random
import re

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
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error("API Key missing! Please add it in Streamlit Advanced Settings.")

# --- HELPERS ---
def extract_index_text(pdf_file, num_pages=20):
    """Extracts text and checks if the PDF is just scanned images."""
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
    Analyze this index text from a {subject_name} textbook. 
    Extract a clean list of individual chapter names.
    Return ONLY a valid JSON array of strings containing the chapter names. Do not include markdown blocks or any conversational text.
    Example output format: ["Chapter 1: Arrival of British", "Chapter 2: Revolt of 1857"]
    Text: {text}
    """
    try:
        response = model.generate_content(prompt)
        # Forcefully find the JSON brackets even if AI talks too much
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Failed to read chapters from AI response. Format error.")
        return ["Error: Could not extract chapters"]

def generate_new_questions(subject, chapter, difficulty, count):
    prompt = f"""
    You are an expert examiner for competitive exams. Generate {count} distinct multiple-choice questions for:
    Subject: {subject}
    Chapter: {chapter}
    Difficulty Level: {difficulty}

    Return your output strictly as a JSON array matching this exact format, with NO extra conversational text at the beginning or end:
    [
      {{
        "id": {random.randint(1000, 9999)},
        "question": "Question text here?",
        "options": {{"A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D"}},
        "correct": "A",
        "explanation": "Detailed explanation.",
        "extra_info": "Extra historical trivia."
      }}
    ]
    """
    try:
        response = model.generate_content(prompt)
        # Forcefully find the JSON data
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(response.text)
    except Exception as e:
        return []

# --- APP LAYOUT ---
st.title("📚 BPSC Smart Quiz Dashboard")
st.markdown("Your custom-tailored preparation engine designed for iPad & Desktop.")
st.write("---")

tab_quiz, tab_history = st.tabs(["🎯 Quiz Playground", "🗄️ Old Generated Questions (Revision)"])

with tab_quiz:
    col_setup, col_display = st.columns([1, 2])
    
    with col_setup:
        st.header("1. Sync Materials")
        sub_input = st.text_input("Subject Name:", value=st.session_state['current_subject'], placeholder="e.g., Indian Polity")
        uploaded_files = st.file_uploader("Upload Chapter/Book PDFs:", type="pdf", accept_multiple_files=True)
        
        if st.button("Extract Chapters"):
            if sub_input and uploaded_files:
                with st.spinner("Processing PDF text..."):
                    combined_chapters = []
                    for f in uploaded_files:
                        raw_index = extract_index_text(f)
                        
                        # NEW CHECK: Warn user if PDF is a scanned image
                        if len(raw_index) < 50:
                            st.warning(f"⚠️ We could not read text from '{f.name}'. It appears to be a scanned image rather than a text document. Try uploading a different PDF or typing chapters manually.")
                            continue
                            
                        chapters = get_chapters_from_ai(raw_index, sub_input)
                        combined_chapters.extend(chapters)
                    
                    if combined_chapters:
                        st.session_state['current_chapters'] = list(set(combined_chapters))
                        st.session_state['current_subject'] = sub_input
                        st.success(f"Loaded {len(st.session_state['current_chapters'])} chapters!")
            else:
                st.error("Please specify a Subject and upload at least one PDF.")
        
        st.write("---")
        st.header("2. Configure Quiz")
        
        selected_ch = st.selectbox("Select Target Chapter:", options=st.session_state['current_chapters'] if st.session_state['current_chapters'] else ["Upload a file first"])
        diff_level = st.selectbox("Difficulty Level:", ["Easy", "Moderate", "Hard", "Very Hard"])
        q_count = st.slider("Number of Questions:", min_value=10, max_value=20, value=10)
        
        if st.button("Generate Mixed Quiz 🔥"):
            if not st.session_state['current_chapters'] or selected_ch == "Upload a file first":
                st.error("Please extract chapters first.")
            else:
                with st.spinner(f"Assembling custom {diff_level} quiz... This takes about 15 seconds..."):
                    matching_old = [q for q in st.session_state['old_questions'] if q['chapter'] == selected_ch]
                    mix_old_count = min(len(matching_old), random.randint(2, 5)) if matching_old else 0
                    fresh_needed = q_count - mix_old_count
                    
                    fresh_qs = generate_new_questions(st.session_state['current_subject'], selected_ch, diff_level, fresh_needed)
                    
                    # NEW CHECK: If generation fails, show an error instead of silently failing
                    if not fresh_qs:
                        st.error("🚨 The AI failed to format the questions correctly. Please click 'Generate Mixed Quiz' again.")
                    else:
                        for q in fresh_qs:
                            q['subject'] = st.session_state['current_subject']
                            q['chapter'] = selected_ch
                            q['difficulty'] = diff_level
                        
                        st.session_state['old_questions'].extend(fresh_qs)
                        
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
            for idx, q in enumerate(st.session_state['active_quiz']):
                st.markdown(f"#### **Q{idx+1}. {q['question']}**")
                opts = q['options']
                formatted_opts = [f"{k}) {v}" for k, v in opts.items()]
                
                user_sel = st.radio(
                    f"Choose your answer for Q{idx+1}:", 
                    options=["Not Answered"] + formatted_opts,
                    key=f"q_{q['id']}_{idx}",
                    label_visibility="collapsed"
                )
                user_answers[idx] = user_sel.split(")")[0] if ")" in user_sel else None
                st.write("")

            if not st.session_state['quiz_submitted']:
                if st.button("Submit Answers & Evaluate"):
                    st.session_state['quiz_submitted'] = True
                    st.rerun()
            else:
                st.success("Evaluation Report Generated below:")
                for idx, q in enumerate(st.session_state['active_quiz']):
                    st.markdown(f"**Question {idx+1}:** {q['question']}")
                    correct_key = q['correct']
                    user_key = user_answers[idx]
                    
                    for k, v in q['options'].items():
                        if k == correct_key:
                            st.markdown(f"🟩 **{k}) {v} (Correct Answer)**")
                        elif k == user_key and user_key != correct_key:
                            st.markdown(f"🟥 **{k}) {v} (Your Selection - Wrong)**")
                        else:
                            st.markdown(f"⚪ {k}) {v}")
                    
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
    st.write(f"Total questions logged: **{len(st.session_state['old_questions'])}**")
    
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
        st.write("No questions recorded yet.")
