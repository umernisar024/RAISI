"""
pages/2_KB_Review.py — Review submitted documents before KB indexing.

Accessible to: admin, reviewer
"""

import os
import sys
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

APP_NAME = os.getenv("APP_NAME", "SI Assistant")

from src.page_auth import require_login, is_reviewer_or_admin
from src.kb_submissions import (
    KB_SUBFOLDERS, KB_FOLDER_LABELS,
    get_pending_submissions, get_all_submissions,
    move_to_kb, reject_submission, get_submission_file_path,
)
from src.security_log import log_event
from src.document_registry import register as registry_register, update as registry_update

# ── Auth check ────────────────────────────────────────────────────────────────
current_user = require_login(allowed_roles=["admin", "reviewer"])

st.set_page_config(page_title=f"KB Review — {APP_NAME}", page_icon="🔍")

st.title("🔍 Knowledge Base Review")
st.caption(
    "Review documents submitted by users. Approved documents are moved to "
    "the appropriate KB folder. Run ingestion separately to index them."
)

# ── Tabs: Pending / All ───────────────────────────────────────────────────────
tab_pending, tab_all = st.tabs(["⏳ Pending Review", "📋 All Submissions"])


def _render_file_download(record: dict, key_prefix: str = "dl") -> None:
    """Show a download button for the file, or a URL link if no file."""
    file_path = get_submission_file_path(record["id"])

    if file_path and file_path.exists():
        file_bytes = file_path.read_bytes()
        st.download_button(
            label="⬇️ Download",
            data=file_bytes,
            file_name=record["original_filename"],
            key=f"{key_prefix}_{record['id']}",
            use_container_width=True,
        )
    elif record.get("url"):
        st.link_button("🔗 Open URL", record["url"], use_container_width=True)
    else:
        st.caption("No file or URL")


def _render_review_form(record: dict) -> None:
    """Inline review form — shown when the reviewer clicks Review."""
    with st.container(border=True):
        st.markdown(f"**Reviewing:** {record['content_name']}")
        st.caption(
            f"Submitted by **{record['submitted_by']}**  "
            f"| Suggested category: **{KB_FOLDER_LABELS.get(record['category'], record['category'])}**"
        )
        if record.get("description"):
            st.write(record["description"])
        if record.get("url"):
            st.caption(f"Source URL: {record['url']}")

        comment = st.text_area(
            "Review comments",
            placeholder="Add notes for the submitter or your team (optional)...",
            key=f"comment_{record['id']}",
            height=80,
        )

        col_folder, col_approve, col_reject = st.columns([3, 2, 1])

        with col_folder:
            folder_labels = [KB_FOLDER_LABELS[f] for f in KB_SUBFOLDERS]
            # Pre-select the category the submitter suggested
            suggested_idx = KB_SUBFOLDERS.index(record["category"]) if record["category"] in KB_SUBFOLDERS else 0
            selected_label = st.selectbox(
                "Move to folder",
                options=folder_labels,
                index=suggested_idx,
                key=f"folder_{record['id']}",
            )
            target_folder = KB_SUBFOLDERS[folder_labels.index(selected_label)]

        with col_approve:
            if st.button(
                "✅ Approve & Move",
                key=f"approve_{record['id']}",
                use_container_width=True,
                type="primary",
            ):
                ok, msg = move_to_kb(
                    submission_id=record["id"],
                    target_folder=target_folder,
                    review_comment=comment,
                    reviewed_by=current_user["username"],
                )
                if ok:
                    log_event(
                        "admin_action",
                        username=current_user["username"],
                        detail=f"KB submission approved: {record['id']} → {target_folder}",
                    )
                    # Pre-populate document registry with submission metadata
                    # so citations are meaningful before/after ingestion
                    registry_register(
                        source_file=record["stored_filename"],
                        title=record.get("content_name", ""),
                        description=record.get("description", ""),
                        url=record.get("url", ""),
                        domain=target_folder,
                        category=KB_FOLDER_LABELS.get(target_folder, target_folder),
                        overwrite=True,
                    )
                    st.success(msg)
                    st.session_state.pop(f"reviewing_{record['id']}", None)
                    st.rerun()
                else:
                    st.error(msg)

        with col_reject:
            if st.button(
                "❌ Reject",
                key=f"reject_{record['id']}",
                use_container_width=True,
            ):
                ok, msg = reject_submission(
                    submission_id=record["id"],
                    review_comment=comment,
                    reviewed_by=current_user["username"],
                )
                if ok:
                    log_event(
                        "admin_action",
                        username=current_user["username"],
                        detail=f"KB submission rejected: {record['id']}",
                    )
                    st.warning(msg)
                    st.session_state.pop(f"reviewing_{record['id']}", None)
                    st.rerun()
                else:
                    st.error(msg)

        if st.button("✕ Cancel", key=f"cancel_{record['id']}"):
            st.session_state.pop(f"reviewing_{record['id']}", None)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PENDING
# ══════════════════════════════════════════════════════════════════════════════

with tab_pending:
    pending = get_pending_submissions()

    if not pending:
        st.info("No documents are waiting for review.")
    else:
        st.caption(f"{len(pending)} document(s) awaiting review")
        st.divider()

        for record in pending:
            col_info, col_cat, col_dl, col_review = st.columns([4, 2, 1, 1])

            with col_info:
                st.markdown(f"**{record['content_name']}**")
                st.caption(
                    f"by {record['submitted_by']} · "
                    f"{record['submitted_at'][:10]}"
                )
                if record.get("description"):
                    st.caption(record["description"][:120] + ("..." if len(record["description"]) > 120 else ""))

            with col_cat:
                st.caption(KB_FOLDER_LABELS.get(record["category"], record["category"]))

            with col_dl:
                _render_file_download(record, key_prefix="pending_dl")

            with col_review:
                if st.button("Review", key=f"open_review_{record['id']}", use_container_width=True, type="primary"):
                    # Toggle the review panel
                    key = f"reviewing_{record['id']}"
                    st.session_state[key] = not st.session_state.get(key, False)
                    st.rerun()

            # Show review form inline if toggled
            if st.session_state.get(f"reviewing_{record['id']}"):
                _render_review_form(record)

            st.divider()

    st.caption(
        "💡 After approving documents, run ingestion to index them: "
        "`python scripts/run_ingestion.py`"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ALL SUBMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab_all:
    all_subs = get_all_submissions()

    if not all_subs:
        st.info("No submissions yet.")
    else:
        # Summary counts
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for s in all_subs:
            counts[s.get("status", "pending")] = counts.get(s.get("status", "pending"), 0) + 1

        c1, c2, c3 = st.columns(3)
        c1.metric("Pending", counts["pending"])
        c2.metric("Approved", counts["approved"])
        c3.metric("Rejected", counts["rejected"])
        st.divider()

        status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}

        for record in reversed(all_subs):  # newest first
            status = record.get("status", "pending")
            icon = status_icon.get(status, "?")

            with st.expander(
                f"{icon} {record['content_name']}  —  "
                f"{record['submitted_at'][:10]}  —  "
                f"{record['submitted_by']}"
            ):
                st.caption(f"ID: {record['id']}  |  Category: {KB_FOLDER_LABELS.get(record['category'], record['category'])}")
                if record.get("description"):
                    st.write(record["description"])
                if record.get("url"):
                    st.caption(f"URL: {record['url']}")
                if record.get("review_comment"):
                    st.info(f"Review comment: {record['review_comment']}")
                if record.get("moved_to"):
                    st.success(f"Moved to: {KB_FOLDER_LABELS.get(record['moved_to'], record['moved_to'])}")
                _render_file_download(record, key_prefix="all_dl")

st.divider()
st.page_link("app.py", label=f"← Back to {APP_NAME}", icon="💬")
