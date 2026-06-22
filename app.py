import streamlit as st
import PyPDF2
import google.generativeai as genai

# --- PAGE SETUP ---
st.set_page_config(page_title="BPSC Smart Quiz", page_icon="📚", layout="wide")

# --- API CONFIGURATION ---
# This securely pulls your API key from Streamlit's Advanced Settings (Secrets)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.warning("API Key not found. Please add GEMINI_API_KEY to your Streamlit Secrets.")

# --- FUNCTIONS ---
def extract_index_text(pdf_file, num_pages=15):
    """Extracts text from the first few pages to find the Table of Contents."""
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    # Only read the first 15 pages to save AI processing time and focus on the index
    pages_to_read = min(len(pdf_reader.pages), num_pages)
    for page_num in range(pages_to_read):
        page = pdf_reader.pages[page_num]
        text += page.extract_text()
    return text

def get_chapters_from_ai(text, subject_name):
    """Asks Gemini to find chapters in the extracted text."""
    prompt = f"""
    You are a helpful assistant for a BPSC exam aspirant. 
    I am providing you the first few pages of a textbook for the subject: {subject_name}.
    Please find the Table of Contents or Index, and list all the chapter names.
    Return ONLY a clean, numbered list of the chapter names. Do not include page numbers or extra chat text.
    
    Text:
    {text}
    """
    response = model.generate_content(prompt)
    return response.text

# --- APP LAYOUT & UI ---
st.title("📚 BPSC Smart Quiz App")
st.markdown("Upload your study materials and generate exam-level quizzes.")

st.divider()

# Two-column layout
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Upload Study Material")
    subject_name = st.text_input("Enter Subject Name (e.g., Modern History, Bihar Special):")
    uploaded_pdfs = st.file_uploader("Upload PDF Documents", type="pdf", accept_multiple_files=True)
    
    if st.button("Process PDFs & Extract Chapters"):
        if not subject_name:
            st.error("Please enter a subject name first.")
        elif not uploaded_pdfs:
            st.error("Please upload at least one PDF.")
        else:
            with st.spinner("Reading PDFs and identifying chapters..."):
                all_chapters = ""
                for pdf in uploaded_pdfs:
                    # Extract text from the start of the book
                    raw_text = extract_index_text(pdf)
                    # Ask AI to parse the chapters
                    chapters = get_chapters_from_ai(raw_text, subject_name)
                    all_chapters += f"**From {pdf.name}:**\n{chapters}\n\n"
                
                # Save the identified chapters to the app's current session memory
                st.session_state['current_chapters'] = all_chapters
                st.session_state['current_subject'] = subject_name
                st.success("Chapters extracted successfully!")

with col2:
    st.subheader("2. Identified Chapters")
    if 'current_chapters' in st.session_state:
        st.info(f"**Subject:** {st.session_state['current_subject']}")
        st.write(st.session_state['current_chapters'])
    else:
        st.write("Upload a PDF and click process to see chapters here.")
