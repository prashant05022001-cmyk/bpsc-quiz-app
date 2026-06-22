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
    model = genai.GenerativeModel('gemini-1.5-flash')
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
    Analyze this text from a {subject_name} book index. Extract all the chapter or topic names.
    Return ONLY a JSON array of strings. Example: ["Topic 1", "Topic 2", "Topic 3"]
    Text: {text}
    """
    try:
        # STRICT JSON MODE: Forces the AI to never make a formatting mistake
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        return []

def generate_new_questions(subject, chapter, difficulty, count):
    prompt = f"""
    You are an expert examiner for competitive exams. Generate {count} distinct multiple-choice questions for:
    Subject: {subject}
    Chapter: {chapter}
    Difficulty Level: {difficulty}

    Return a JSON array matching this EXACT schema:
    [
      {{
        "id": {random.randint(1000, 9999)},
        "question": "Question text here?",
        "options": {{"A": "Option A text", "B": "Option B text", "C": "Option C text", "D": "Option D text"}},
        "correct": "A",
        "explanation": "Detailed explanation.",
        "extra_info": "Extra historical trivia."
      }}
    ]
    """
    try:
        # STRICT JSON MODE
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
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
        
        st.write("---")
        st.subheader("Option A: Extract from PDF")
        uploaded_files = st.file_uploader("Upload Chapter/Book PDFs:", type="pdf", accept_multiple_files=True)
        
        if st.button("Extract Chapters via AI"):
            if sub_input and uploaded_files:
                with st.spinner("Processing PDF text..."):
                    combined_chapters = []
                    for f in uploaded_files:
                        raw_index = extract_index_text(f)
                        chapters = get_chapters_from_ai(raw_index, sub_input)
                        if chapters:
                            combined_chapters.extend(chapters)
                        else:
                            st.error(f"❌ Failed to read '{f.name}'. The formatting is too complex. Please use Option B below.")
                    
                    if combined_chapters:
                        st.session_state['current_chapters'] = list(set(combined_chapters))
                        st.session_state['current_subject'] = sub_input
                        st.success(f"Loaded {len(st.session_state['current_chapters'])} chapters!")
            else:
                st.error("Please specify a Subject and upload at least one PDF.")
                
        st.write("---")
        st.subheader("Option B: Enter Manually (For Heavy PDFs)")
        st.markdown("*Use this for heavy files like Vision IAS magazines where AI extraction fails.*")
        manual_chapters = st.text_area("Paste chapter names here (one per line):", placeholder="Advent of Europeans\nRevolt of 1857\nIndian National Congress")
        
        if st.button("Save Manual Chapters"):
            if sub_input and manual_chapters:
                chapters = [line.strip() for line in manual_chapters.split('\n') if line.strip()]
                st.session_state['current_chapters'] = list(set(st.session_state['current_chapters'] + chapters))
                st.session_state['current_subject'] = sub_input
                st.success(f"Successfully added {len(chapters)} manual chapters!")
            else:
                st.error("Please enter a subject name and at least one chapter.")
        
        st.write("---")
        st.header("2. Configure Quiz")
        
        selected_ch = st.selectbox("Select Target Chapter:", options=st.session_state['current_chapters'] if st.session_state['current_chapters'] else ["Add chapters first"])
        diff_level = st.selectbox("Difficulty Level:", ["Easy", "Moderate", "Hard", "Very Hard"])
        q_count = st.slider("Number of Questions:", min_value=10, max_value=20, value=10)
        
        if st.button("Generate Mixed Quiz 🔥"):
            if not st.session_state['current_chapters'] or selected_ch == "Add chapters first":
                st.error("Please add chapters first using Option A or Option B.")
            else:
                with st.spinner(f"Assembling custom {diff_level} quiz..."):
                    matching_old = [q for q in st.session_state['old_questions'] if q['chapter'] == selected_ch]
                    mix_old_count = min(len(matching_old), random.randint(2, 5)) if matching_old else 0
                    fresh_needed = q_count - mix_old_count
                    
                    fresh_qs = generate_new_questions(st.session_state['current_subject'], selected_ch, diff_level, fresh_needed)
                    
                    if not fresh_qs:
                        st.error("🚨 Network error. Please click 'Generate Mixed Quiz' again.")
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
