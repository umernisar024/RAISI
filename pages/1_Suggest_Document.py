"""
pages/1_Suggest_Document.py — Submit a document for KB review.

Any logged-in user can suggest a document. Uploaded files are saved to
data/raw/to_be_reviewed/ and will NOT be ingested until a reviewer or admin
approves and moves them to an appropriate KB folder.
"""

import sys
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from src.page_auth import require_login
from src.kb_submissions import (
    KB_SUBFOLDERS, KB_FOLDER_LABELS, SUPPORTED_UPLOAD_TYPES,
    MAX_UPLOAD_MB, save_submission, ensure_kb_dirs,
)

# ── Auth check ────────────────────────────────────────────────────────────────
current_user = require_login()  # any logged-in user may submit

st.set_page_config(page_title="Suggest a Document — SI Assistant", page_icon="📄")

st.title("📄 Suggest a Document")
st.caption(
    "Suggest a document or resource to be added to the knowledge base. "
    "A reviewer will check it before it is indexed."
)
st.divider()

ensure_kb_dirs()

# ── Submission form ───────────────────────────────────────────────────────────
with st.form("suggest_doc_form", clear_on_submit=True):

    content_name = st.text_input(
        "Document / Resource name *",
        placeholder="e.g. WHO Digital Health Strategy Toolkit 2023",
        help="A clear, descriptive name for this resource.",
    )

    description = st.text_area(
        "Short description *",
        placeholder="Briefly describe what this document covers and why it is relevant.",
        height=100,
    )

    url = st.text_input(
        "URL (if available)",
        placeholder="https://www.who.int/publications/...",
        help="Link to the original source. Leave blank if you are uploading a file.",
    )

    # Build dropdown from KB_SUBFOLDERS (excluding staging)
    category_options = {
        KB_FOLDER_LABELS[f]: f for f in KB_SUBFOLDERS
    }
    selected_label = st.selectbox(
        "Category *",
        options=list(category_options.keys()),
        help="Which knowledge base category best fits this document?",
    )
    selected_folder = category_options[selected_label]

    uploaded_file = st.file_uploader(
        f"Upload file (optional — PDF, Word, TXT, MD — max {MAX_UPLOAD_MB} MB)",
        type=[ext.lstrip(".") for ext in SUPPORTED_UPLOAD_TYPES],
        help=f"Maximum file size: {MAX_UPLOAD_MB} MB",
    )

    submitted = st.form_submit_button("📤 Submit for Review", use_container_width=True)

if submitted:
    # Validation
    errors = []
    if not content_name.strip():
        errors.append("Document name is required.")
    if not description.strip():
        errors.append("Description is required.")
    if not url.strip() and uploaded_file is None:
        errors.append("Please provide either a URL or upload a file.")
    if uploaded_file is not None:
        size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            errors.append(f"File is {size_mb:.1f} MB — maximum is {MAX_UPLOAD_MB} MB.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        file_bytes = uploaded_file.getvalue() if uploaded_file else b""
        filename = uploaded_file.name if uploaded_file else f"{content_name[:40].replace(' ', '_')}.url"

        record = save_submission(
            file_bytes=file_bytes,
            original_filename=filename,
            content_name=content_name.strip(),
            description=description.strip(),
            url=url.strip(),
            category=selected_folder,
            submitted_by=current_user["username"],
        )

        st.success(
            f"Thank you! Your submission has been received and will be reviewed by the team. "
            f"(Reference: {record['id']})"
        )
        st.caption(
            "Once reviewed and approved, the document will be added to the "
            f"**{KB_FOLDER_LABELS[selected_folder]}** category and indexed."
        )

st.divider()
st.page_link("app.py", label="← Back to chat", icon="💬")
