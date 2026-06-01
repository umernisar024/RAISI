"""
app.py — Streamlit chatbot UI for SIAgent.

Usage:
    streamlit run app.py

Roles:
    admin — full access: system prompt, user management, feedback log, all settings
    user  — chat, persona selection, response rating and feedback
"""

import csv
import io
import os
import re
import subprocess
import sys
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Configurable branding ─────────────────────────────────────────────────────
# Set these in .env to rebrand the UI without touching any code.
# APP_NAME     — shown in the browser tab, login page, and chat header
# APP_SUBTITLE — shown on the login page below the name
# APP_ICON     — emoji used in the browser tab and page headers
APP_NAME     = os.getenv("APP_NAME",     "SI Assistant")
APP_SUBTITLE = os.getenv("APP_SUBTITLE", "Digital Health Standards & Interoperability Assistant")
APP_ICON     = os.getenv("APP_ICON",     "🏥")

from src.chat import RAGChat, load_system_prompt, DEFAULT_SYSTEM_PROMPT_PATH
from src.embedder import Embedder
from src.store import VectorStore
from src.auth import authenticate, get_all_users, add_user, delete_user, change_password
from src.feedback import save_feedback, load_feedback, feedback_summary
from src.security_log import log_event, load_security_log
from src.rate_limiter import check_limit, record_question, get_all_usage_today, get_limit, reset_user_today
from src.suggestions import is_not_found, generate_suggestions
from src.kb_submissions import KB_SUBFOLDERS


# ── Server-level cache — loaded ONCE, shared across all user sessions ─────────
# @st.cache_resource persists for the lifetime of the Streamlit server process.
# This means the 3-5 second model load happens once on first request,
# then every subsequent login is near-instant.

@st.cache_resource(show_spinner="Loading knowledge base models... (first time only)")
def load_shared_resources():
    embedder = Embedder()
    store = VectorStore()
    return embedder, store


# ── Persona definitions ───────────────────────────────────────────────────────

PERSONAS = {
    "Select your role...": {
        "icon": "💬",
        "description": "",
        "prompt": "",
    },
    "Policy Maker": {
        "icon": "🏛️",
        "description": "Ministry / Department of Health — decisions, strategy, investment",
        "prompt": """
AUDIENCE CONTEXT — POLICY MAKER:
The user is a policy maker such as a Director, Chief Digital Health Officer, or Ministry of Health official responsible for digital health strategy, investment decisions, and governance. Tailor your response:
- Use plain, non-technical language. Avoid acronyms unless defined.
- Focus on outcomes, strategic alignment, governance implications, and investment rationale.
- Reference international guidance from WHO, World Bank, or regional bodies where relevant.
- Keep the response decision-enabling. What does this person need to know to act?
- Avoid implementation details, code, or technical specifications unless directly asked.
""",
    },
    "Implementer": {
        "icon": "⚙️",
        "description": "Developer / Development Partner — building and deploying solutions",
        "prompt": """
AUDIENCE CONTEXT — IMPLEMENTER:
The user is a technical implementer such as a software developer, solution architect, or development partner building digital health solutions. Tailor your response:
- Use precise technical language. Acronyms and standards terminology are welcome.
- Focus on practical implementation: FHIR resources, API patterns, integration approaches.
- Provide actionable step-by-step guidance where relevant.
- Reference implementation guides, technical specifications, and open source tools.
- Be specific — vague guidance is not useful to someone building a system.
""",
    },
    "Practitioner": {
        "icon": "🩺",
        "description": "Clinician / Health Worker — doctor, nurse, midwife, community health worker",
        "prompt": """
AUDIENCE CONTEXT — PRACTITIONER:
The user is a clinical practitioner such as a doctor, nurse, midwife, or community health worker interacting with health systems at the point of care. Tailor your response:
- Use plain clinical language. Avoid deep technical or policy jargon.
- Focus on workflow impact, usability, and direct clinical relevance.
- Relate answers to patient care and day-to-day practice.
- Do not assume technical knowledge of systems or standards.
""",
    },
    "Academia": {
        "icon": "🎓",
        "description": "Student / Researcher / Teacher — learning and advancing the field",
        "prompt": """
AUDIENCE CONTEXT — ACADEMIA:
The user is from an academic background — a student, researcher, or lecturer studying digital health systems and interoperability. Tailor your response:
- Balance conceptual explanation with practical examples.
- Introduce and define frameworks, standards, and theoretical foundations clearly.
- Reference source documents and organisations where relevant.
- Encourage deeper exploration and note where there is ongoing debate or evolving practice.
- Use a teaching tone: explain the why behind things, not just the what.
""",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_system_prompt(base: str, persona_key: str) -> str:
    addon = PERSONAS.get(persona_key, {}).get("prompt", "").strip()
    return f"{base}\n\n{addon}" if addon else base


def plain_text(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title=APP_NAME,
    page_icon=APP_ICON,
    layout="wide",
)

# ── Layout CSS ────────────────────────────────────────────────────────────────
# Always inject the bottom-padding fix for the sticky chat input.
st.markdown("""
<style>
section.main > div.block-container {
    padding-bottom: 90px !important;
}
</style>
""", unsafe_allow_html=True)

# Hide the multipage sidebar nav and the entire sidebar until the user has
# logged in — blank white screen before login.  Kept as a SEPARATE markdown
# call (not embedded in an f-string) so curly braces in the CSS are literal
# and not misinterpreted as f-string escape sequences.
if not st.session_state.get("logged_in", False):
    st.markdown("""
<style>
[data-testid="stSidebarNav"],
[data-testid="stSidebar"],
section[data-testid="stSidebar"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN SCREEN
# ══════════════════════════════════════════════════════════════════════════════

_MAX_LOGIN_ATTEMPTS = 5      # lockout after this many consecutive failures
_LOCKOUT_SECONDS = 300       # 5 minutes


def show_login():
    # Initialise attempt tracking in session state
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0
    if "lockout_until" not in st.session_state:
        st.session_state.lockout_until = None

    st.markdown("<br><br>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(f"## {APP_ICON} {APP_NAME}")
        st.markdown(f"##### {APP_SUBTITLE}")
        st.divider()

        # Check lockout
        import time
        now = time.time()
        if st.session_state.lockout_until and now < st.session_state.lockout_until:
            remaining = int(st.session_state.lockout_until - now)
            st.error(f"Too many failed attempts. Please wait {remaining} seconds before trying again.")
            return

        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            # Basic input validation
            if not username.strip() or not password:
                st.error("Please enter your username and password.")
                return

            user = authenticate(username.strip(), password)
            if user:
                st.session_state.logged_in = True
                st.session_state.current_user = user
                st.session_state.login_attempts = 0
                st.session_state.lockout_until = None
                log_event("successful_login", username=username.strip())
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                log_event(
                    "failed_login",
                    username=username.strip(),
                    detail=f"attempt {st.session_state.login_attempts} of {_MAX_LOGIN_ATTEMPTS}",
                )
                remaining_attempts = _MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts
                if st.session_state.login_attempts >= _MAX_LOGIN_ATTEMPTS:
                    st.session_state.lockout_until = time.time() + _LOCKOUT_SECONDS
                    log_event("account_locked", username=username.strip(),
                              detail=f"locked for {_LOCKOUT_SECONDS}s after {_MAX_LOGIN_ATTEMPTS} failures")
                    st.error("Too many failed attempts. Account locked for 5 minutes.")
                else:
                    st.error(
                        f"Incorrect username or password. "
                        f"{remaining_attempts} attempt{'s' if remaining_attempts != 1 else ''} remaining."
                    )


if not st.session_state.get("logged_in"):
    show_login()
    st.stop()

# ── Session idle timeout ───────────────────────────────────────────────────────
# Auto-logout after SESSION_TIMEOUT_MINUTES of inactivity (default 120 min).
# last_activity is updated on every page render, so any interaction resets
# the timer.  A stale open browser tab is logged out on its next refresh.
import time as _time
_SESSION_TIMEOUT_SECS = int(os.getenv("SESSION_TIMEOUT_MINUTES", "120")) * 60
_now = _time.time()

if "last_activity" not in st.session_state:
    st.session_state.last_activity = _now
elif _now - st.session_state.last_activity > _SESSION_TIMEOUT_SECS:
    _expired_user = st.session_state.get("current_user", {}).get("username", "unknown")
    log_event("session_expired", username=_expired_user,
              detail=f"idle for >{_SESSION_TIMEOUT_SECS // 60} min")
    for _k in ["logged_in", "current_user", "rag", "messages",
               "active_persona", "system_prompt_text", "ratings", "last_activity"]:
        st.session_state.pop(_k, None)
    st.warning("⏱ Your session has expired due to inactivity. Please log in again.")
    st.rerun()
else:
    st.session_state.last_activity = _now


# ── Convenience shortcuts after login ─────────────────────────────────────────
current_user = st.session_state.current_user
is_admin = current_user["role"] == "admin"

# Load shared resources here so _embedder and _store are always defined
# before the sidebar or any other UI element references them.
_embedder, _store = load_shared_resources()


# ══════════════════════════════════════════════════════════════════════════════
# SHARED SIDEBAR ELEMENTS
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:

    # User info + logout
    _role_label = {"admin": "Admin", "reviewer": "Reviewer", "user": "User"}.get(
        current_user.get("role", "user"), "User"
    )
    st.markdown(f"**{current_user['name']}** ({_role_label})")
    if st.button("🚪 Sign out", use_container_width=True):
        for key in ["logged_in", "current_user", "rag", "messages",
                    "active_persona", "system_prompt_text", "ratings"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()

    # ── Persona selector (everyone) ───────────────────────────────────────────
    st.subheader("👤 Your Role")
    selected_persona = st.selectbox(
        "Who are you?",
        options=list(PERSONAS.keys()),
        index=0,
        key="persona_select",
    )
    if selected_persona != "Select your role...":
        p = PERSONAS[selected_persona]
        st.caption(f"{p['icon']}  {p['description']}")

    if "active_persona" not in st.session_state:
        st.session_state.active_persona = selected_persona

    if selected_persona != st.session_state.active_persona:
        st.session_state.active_persona = selected_persona
        if st.session_state.get("rag"):
            base = st.session_state.get("system_prompt_text") or load_system_prompt()
            st.session_state.rag.system_prompt = build_system_prompt(base, selected_persona)
            st.session_state.rag.reset()
        st.session_state.messages = []
        st.rerun()

    st.divider()

    n_results = st.slider("Chunks to retrieve", min_value=1, max_value=10, value=5)

    st.divider()

    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.get("rag"):
            st.session_state.rag.reset()
        st.rerun()

    # ── Daily usage counter (non-admin users only) ────────────────────────────
    if not is_admin:
        daily_limit = get_limit()
        if daily_limit > 0:
            _allowed, _used, _limit = check_limit(
                current_user["username"], current_user["role"]
            )
            _remaining = max(0, _limit - _used)
            st.divider()
            if _remaining == 0:
                st.error(f"Daily limit reached ({_limit} questions). Resets at midnight.")
            elif _remaining <= 5:
                st.warning(f"⚠️ {_remaining} questions remaining today")
            else:
                st.caption(f"💬 {_remaining} of {_limit} questions remaining today")

    # ── Admin-only controls ───────────────────────────────────────────────────
    if is_admin:

        st.divider()

        # KB stats
        st.subheader("📚 Knowledge Base")

        @st.cache_data(ttl=60)
        def get_stats():
            return _store.stats()

        stats = get_stats()
        col_a, col_b = st.columns(2)
        col_a.metric("Indexed chunks", stats["total_chunks"])
        col_b.metric("SSCP chunks", stats.get("sscp_chunks", 0))

        if stats["by_domain"]:
            st.caption("**By domain**")
            for domain, count in sorted(stats["by_domain"].items()):
                st.caption(f"{domain}: {count}")

        if stats.get("by_language"):
            st.caption("**By language**")
            for lang, count in sorted(stats["by_language"].items()):
                st.caption(f"{lang}: {count}")

        st.divider()

        st.subheader("🤖 Agent Instructions")

        if "system_prompt_text" not in st.session_state:
            st.session_state.system_prompt_text = load_system_prompt()

        edited_prompt = st.text_area(
            "Base agent instructions:",
            value=st.session_state.system_prompt_text,
            height=220,
            key="prompt_editor",
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save", use_container_width=True):
                DEFAULT_SYSTEM_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
                DEFAULT_SYSTEM_PROMPT_PATH.write_text(edited_prompt, encoding="utf-8")
                st.session_state.system_prompt_text = edited_prompt
                if st.session_state.get("rag"):
                    st.session_state.rag.system_prompt = build_system_prompt(
                        edited_prompt, st.session_state.active_persona
                    )
                    st.session_state.rag.reset()
                log_event("admin_action", username=current_user["username"],
                          detail="system_prompt updated")
                st.success("Saved!")
        with col2:
            if st.button("↩ Reset", use_container_width=True):
                st.session_state.system_prompt_text = load_system_prompt()
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE — RAG ENGINE
# ══════════════════════════════════════════════════════════════════════════════

if "messages" not in st.session_state:
    st.session_state.messages = []
if "ratings" not in st.session_state:
    st.session_state.ratings = {}   # msg_index → {"rating": str, "comment": str}
if "active_persona" not in st.session_state:
    st.session_state.active_persona = selected_persona

if "rag" not in st.session_state or st.session_state.rag is None:
    base = st.session_state.get("system_prompt_text") or load_system_prompt()
    rag = RAGChat(
        system_prompt=build_system_prompt(base, st.session_state.active_persona),
        embedder=_embedder,
        store=_store,
    )
    rag.n_results = n_results
    st.session_state.rag = rag

st.session_state.rag.n_results = n_results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════

persona = PERSONAS.get(st.session_state.active_persona, {})
st.title(f"{APP_ICON} {APP_NAME}")

if persona.get("description"):
    st.caption(
        f"{persona['icon']} Responding as: **{st.session_state.active_persona}** "
        f"— {persona['description']}"
    )

# ── Chat input — at PAGE LEVEL so Streamlit keeps it fixed at the bottom ─────
# Must be defined BEFORE tabs so it stays sticky regardless of tab content.

prompt = st.chat_input("Ask a question ...")

# ── Intercept a suggestion the user clicked in the previous rerun ─────────────
# When a suggestion button is clicked, it sets pending_suggestion in session
# state and reruns. We pick it up here so it flows through the same handler
# as a typed prompt, including rate-limit checks and history recording.
if not prompt and "pending_suggestion" in st.session_state:
    prompt = st.session_state.pop("pending_suggestion")

# ── Tabs (admin) or plain container (user) ────────────────────────────────────
if is_admin:
    tab_chat, tab_users, tab_feedback, tab_security, tab_kb = st.tabs(
        ["💬 Chat", "👥 User Management", "📊 Feedback Log", "🔒 Security Log", "📥 Ingestion"]
    )
else:
    tab_chat = st.container()


# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK WIDGET — @st.fragment so rating a response reruns ONLY this widget,
# not the whole page. This makes 👍 / 👎 respond in under 1 second.
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def feedback_widget(idx: int, question: str, answer_text: str,
                    username: str, role: str, persona_key: str):
    existing = st.session_state.ratings.get(idx)

    if existing:
        st.caption(
            f"You rated this: {existing['rating']}"
            + (f"  —  \"{existing['comment']}\"" if existing.get("comment") else "")
        )
        return

    r_col1, r_col2, _ = st.columns([1, 1, 6])
    with r_col1:
        if st.button("👍 Helpful", key=f"up_{idx}", use_container_width=True):
            st.session_state.ratings[idx] = {"rating": "👍 Helpful", "comment": ""}
            save_feedback(
                username=username, user_role=role, persona=persona_key,
                question=question, answer=answer_text, rating="👍 Helpful",
            )
            st.rerun(scope="fragment")
    with r_col2:
        if st.button("👎 Not helpful", key=f"down_{idx}", use_container_width=True):
            st.session_state[f"show_comment_{idx}"] = True
            st.rerun(scope="fragment")

    if st.session_state.get(f"show_comment_{idx}"):
        with st.form(key=f"comment_form_{idx}"):
            comment = st.text_area(
                "What was wrong or missing? (optional)",
                key=f"comment_{idx}",
                height=80,
            )
            if st.form_submit_button("Submit feedback"):
                st.session_state.ratings[idx] = {"rating": "👎 Not helpful", "comment": comment}
                save_feedback(
                    username=username, user_role=role, persona=persona_key,
                    question=question, answer=answer_text,
                    rating="👎 Not helpful", comment=comment,
                )
                st.session_state.pop(f"show_comment_{idx}", None)
                st.rerun(scope="fragment")


def _to_csv(rows: list[dict]) -> bytes:
    """Convert a list of dicts to a UTF-8 CSV byte string (opens in Excel)."""
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys(), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 correctly


def _render_sources(sources: list[dict]):
    with st.expander(f"Sources ({len(sources)} chunks retrieved)"):
        for i, r in enumerate(sources, 1):
            meta = r["metadata"]
            st.caption(
                f"{i}. {meta.get('source_file', 'unknown')} "
                f"— page {meta.get('page_number', 'N/A')} "
                f"— score {r['score']:.3f}"
            )
            st.write(r["text"][:400] + ("..." if len(r["text"]) > 400 else ""))
            if i < len(sources):
                st.divider()


def _render_suggestions(idx: int, suggestions: list[str]):
    """
    Render alternative question buttons below a 'not found' response.
    Only shown for the most recent assistant message so old suggestions
    don't clutter the conversation history.
    Clicking a button stores it as pending_suggestion and reruns the page,
    where it is picked up and processed as a normal typed prompt.
    """
    st.divider()
    st.caption("Here are some related questions I can help with:")

    for i, suggestion in enumerate(suggestions):
        if st.button(
            suggestion,
            key=f"sugg_{idx}_{i}",
            use_container_width=True,
        ):
            st.session_state["pending_suggestion"] = suggestion
            st.rerun()

    # "Something else" — free-text fallback
    with st.form(key=f"sugg_other_{idx}", clear_on_submit=True):
        other = st.text_input(
            "Or type your own question:",
            placeholder="Something else...",
            label_visibility="collapsed",
        )
        if st.form_submit_button("Ask →", use_container_width=True):
            if other.strip():
                st.session_state["pending_suggestion"] = other.strip()
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CHAT
# ══════════════════════════════════════════════════════════════════════════════

with tab_chat:

    if is_admin and stats["total_chunks"] == 0:
        st.warning("⚠️ Knowledge base is empty. Go to the **📥 Ingestion** tab to index your documents.")

    if not st.session_state.messages:
        if st.session_state.active_persona == "Select your role...":
            st.info("Select your role in the sidebar to get responses tailored to your context.")
        else:
            hints = {
                "Policy Maker": "Try: What are the key components of a national digital health strategy?",
                "Implementer":  "Try: How do I implement a FHIR-based patient identity service?",
                "Practitioner": "Try: How does a shared health record affect my clinical workflow?",
                "Academia":     "Try: What is the theoretical basis for the OpenHIE architecture?",
            }
            st.info(hints.get(st.session_state.active_persona,
                              "Ask me anything about digital health, interoperability, or standards."))

    # ── Render conversation history ───────────────────────────────────────────
    last_idx = len(st.session_state.messages) - 1
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.write(plain_text(msg["content"]))

            if msg.get("sources"):
                _render_sources(msg["sources"])

            if msg["role"] == "assistant":
                prev_content = st.session_state.messages[idx - 1]["content"] if idx > 0 else ""
                feedback_widget(
                    idx=idx,
                    question=prev_content,
                    answer_text=msg["content"],
                    username=current_user["username"],
                    role=current_user["role"],
                    persona_key=st.session_state.active_persona,
                )

                # Show suggestion buttons only for the most recent not-found response
                if msg.get("suggestions") and idx == last_idx:
                    _render_suggestions(idx, msg["suggestions"])

    # ── Handle new prompt (received from the page-level chat_input above) ─────
    if prompt:
        # A03 — input validation
        if len(prompt) > 2000:
            st.warning("Question is too long. Please keep it under 2000 characters.")
            st.stop()
        prompt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", prompt).strip()
        if not prompt:
            st.stop()

        # ── Daily question limit check ────────────────────────────────────────
        _allowed, _used, _limit = check_limit(
            current_user["username"], current_user["role"]
        )
        if not _allowed:
            st.error(
                f"You have reached your daily limit of {_limit} questions. "
                f"Your limit resets at midnight. Please come back tomorrow."
            )
            st.stop()

        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            try:
                sources, stream_gen = st.session_state.rag.stream_chat(prompt)
            except Exception as e:
                st.error("Something went wrong generating the response. Please try again.")
                log_event("chat_error", username=current_user["username"], detail=str(e)[:200])
                st.stop()

            # Stream response — text appears token-by-token, feels instant
            output = st.empty()
            full_text = ""
            for chunk in stream_gen:
                full_text += chunk
                output.write(plain_text(full_text))

            # Save to RAG history after streaming completes
            st.session_state.rag.add_to_history(prompt, plain_text(full_text))

            # Record question against daily limit (after successful response)
            record_question(current_user["username"])

            if sources:
                _render_sources(sources)

            # ── Suggestion generation (only on "not found" responses) ─────────
            suggestions = []
            if is_not_found(full_text):
                with st.spinner("Finding related questions..."):
                    suggestions = generate_suggestions(prompt, sources)

        st.session_state.messages.append({
            "role": "assistant",
            "content": full_text,
            "sources": sources,
            "suggestions": suggestions,
        })
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — USER MANAGEMENT (admin only)
# ══════════════════════════════════════════════════════════════════════════════

if is_admin:
    with tab_users:
        st.subheader("Current users")

        users = get_all_users()
        _daily_limit = get_limit()
        _usage_today = get_all_usage_today()

        for u in users:
            col_name, col_role, col_usage, col_reset, col_del = st.columns([3, 1, 1, 1, 1])
            _used_today = _usage_today.get(u["username"], 0)
            with col_name:
                st.write(f"**{u['name']}** (`{u['username']}`)")
            with col_role:
                st.caption(u["role"])
            with col_usage:
                if u["role"] == "admin" or _daily_limit == 0:
                    st.caption("unlimited")
                else:
                    _pct = _used_today / _daily_limit
                    _color = "🔴" if _pct >= 1.0 else "🟡" if _pct >= 0.8 else "🟢"
                    st.caption(f"{_color} {_used_today}/{_daily_limit}")
            with col_reset:
                if u["role"] != "admin" and _daily_limit > 0:
                    if st.button("↺ Reset", key=f"reset_{u['username']}", help="Reset today's question count"):
                        reset_user_today(u["username"])
                        log_event("admin_action", username=current_user["username"],
                                  detail=f"reset daily limit for: {u['username']}")
                        st.toast(f"Reset usage for {u['username']}")
                        st.rerun()
            with col_del:
                if u["username"] != "admin":
                    if st.button("🗑️ Delete", key=f"del_{u['username']}"):
                        ok, msg = delete_user(u["username"])
                        if ok:
                            log_event("user_deleted", username=current_user["username"],
                                      detail=f"deleted user: {u['username']}")
                        st.toast(msg)
                        st.rerun()
                else:
                    st.caption("protected")

        st.divider()
        st.subheader("Add new user")

        with st.form("add_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_username = st.text_input("Username")
                new_name = st.text_input("Full name")
            with col2:
                new_password = st.text_input("Password", type="password")
                new_role = st.selectbox("Role", ["user", "reviewer", "admin"])
            if st.form_submit_button("Add user", use_container_width=True):
                ok, msg = add_user(new_username, new_password, new_role, new_name)
                if ok:
                    log_event("user_created", username=current_user["username"],
                              detail=f"created user: {new_username} role: {new_role}")
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.divider()
        st.subheader("Change password")

        with st.form("change_pw_form", clear_on_submit=True):
            usernames = [u["username"] for u in users]
            target = st.selectbox("User", usernames)
            new_pw = st.text_input("New password", type="password")
            if st.form_submit_button("Update password", use_container_width=True):
                ok, msg = change_password(target, new_pw)
                if ok:
                    log_event("password_changed", username=current_user["username"],
                              detail=f"changed password for: {target}")
                st.success(msg) if ok else st.error(msg)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — FEEDBACK LOG (admin only)
# ══════════════════════════════════════════════════════════════════════════════

if is_admin:
    with tab_feedback:

        summary = feedback_summary()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total ratings", summary["total"])
        m2.metric("👍 Helpful", summary["helpful"])
        m3.metric("👎 Not helpful", summary["not_helpful"])
        m4.metric("Satisfaction", f"{summary['pct_helpful']}%")

        st.divider()

        # ── Export and clear actions ──────────────────────────────────────────
        _all_feedback = load_feedback(limit=100_000)   # load all for export
        _fcol1, _fcol2, _fcol3 = st.columns([2, 2, 4])

        with _fcol1:
            st.download_button(
                label="⬇️ Download as CSV",
                data=_to_csv(_all_feedback),
                file_name="feedback_log.csv",
                mime="text/csv",
                disabled=not _all_feedback,
                use_container_width=True,
            )

        with _fcol2:
            if st.button("🗑️ Clear all feedback", use_container_width=True,
                         disabled=not _all_feedback):
                st.session_state["confirm_clear_feedback"] = True

        if st.session_state.get("confirm_clear_feedback"):
            st.warning("This will permanently delete all feedback entries. Are you sure?")
            _cc1, _cc2 = st.columns(2)
            with _cc1:
                if st.button("✅ Yes, clear feedback", type="primary", use_container_width=True):
                    from src.feedback import FEEDBACK_FILE
                    FEEDBACK_FILE.unlink(missing_ok=True)
                    log_event("admin_action", username=current_user["username"],
                              detail="feedback log cleared")
                    st.session_state.pop("confirm_clear_feedback", None)
                    st.toast("Feedback log cleared.")
                    st.rerun()
            with _cc2:
                if st.button("✕ Cancel", use_container_width=True):
                    st.session_state.pop("confirm_clear_feedback", None)
                    st.rerun()

        st.divider()

        entries = load_feedback(limit=50)
        if not entries:
            st.info("No feedback submitted yet.")
        else:
            st.caption(f"Showing {len(entries)} most recent entries (download CSV for full log)")
            for e in entries:
                icon = "👍" if "👍" in e.get("rating", "") else "👎"
                with st.expander(
                    f"{icon}  {e['timestamp']}  —  {e.get('persona', '')}  "
                    f"({e.get('username', 'unknown')})"
                ):
                    st.write(f"**Question:** {e.get('question', '')}")
                    st.write(f"**Answer:** {e.get('answer', '')[:300]}...")
                    if e.get("comment"):
                        st.write(f"**Feedback comment:** {e['comment']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SECURITY LOG (admin only)
# ══════════════════════════════════════════════════════════════════════════════


if is_admin:
    with tab_security:

        sec_entries = load_security_log(limit=100_000)   # all for counts + export

        # Summary counts
        event_types = {}
        for e in sec_entries:
            ev = e.get("event", "unknown")
            event_types[ev] = event_types.get(ev, 0) + 1

        failed = event_types.get("failed_login", 0)
        locked = event_types.get("account_locked", 0)
        admin_actions = event_types.get("admin_action", 0) + \
                        event_types.get("user_created", 0) + \
                        event_types.get("user_deleted", 0) + \
                        event_types.get("password_changed", 0)

        c1, c2, c3 = st.columns(3)
        c1.metric("Failed logins", failed)
        c2.metric("Lockouts", locked)
        c3.metric("Admin actions", admin_actions)

        st.divider()

        # ── Export and clear actions ──────────────────────────────────────────
        _scol1, _scol2, _scol3 = st.columns([2, 2, 4])

        with _scol1:
            st.download_button(
                label="⬇️ Download as CSV",
                data=_to_csv(list(reversed(sec_entries))),  # oldest first for CSV
                file_name="security_log.csv",
                mime="text/csv",
                disabled=not sec_entries,
                use_container_width=True,
            )

        with _scol2:
            if st.button("🗑️ Clear security log", use_container_width=True,
                         disabled=not sec_entries):
                st.session_state["confirm_clear_security"] = True

        if st.session_state.get("confirm_clear_security"):
            st.warning("This will permanently delete all security log entries. Are you sure?")
            _sc1, _sc2 = st.columns(2)
            with _sc1:
                if st.button("✅ Yes, clear log", type="primary", use_container_width=True):
                    from src.security_log import SECURITY_LOG_FILE
                    SECURITY_LOG_FILE.unlink(missing_ok=True)
                    log_event("admin_action", username=current_user["username"],
                              detail="security log cleared")
                    st.session_state.pop("confirm_clear_security", None)
                    st.toast("Security log cleared.")
                    st.rerun()
            with _sc2:
                if st.button("✕ Cancel ", use_container_width=True):  # trailing space avoids key clash
                    st.session_state.pop("confirm_clear_security", None)
                    st.rerun()

        st.divider()

        # Show most recent 100 in the UI
        sec_entries_display = sec_entries[:100]
        if not sec_entries_display:
            st.info("No security events recorded yet.")
        else:
            st.caption(f"Showing {len(sec_entries_display)} most recent events (download CSV for full log)")
            EVENT_ICONS = {
                "failed_login": "⚠️",
                "account_locked": "🔒",
                "successful_login": "✅",
                "admin_action": "🛠️",
                "user_created": "👤",
                "user_deleted": "🗑️",
                "password_changed": "🔑",
                "chat_error": "❌",
            }
            for e in sec_entries_display:
                icon = EVENT_ICONS.get(e.get("event", ""), "•")
                label = (
                    f"{icon} {e['timestamp']}  —  "
                    f"{e.get('event', '').replace('_', ' ').title()}  "
                    f"({e.get('username', '—')})"
                )
                with st.expander(label):
                    if e.get("detail"):
                        st.caption(e["detail"])
                    if e.get("ip"):
                        st.caption(f"IP: {e['ip']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — INGESTION (admin only)
# ══════════════════════════════════════════════════════════════════════════════

if is_admin:
    with tab_kb:

        st.subheader("📥 Run Knowledge Base Ingestion")
        st.caption(
            "Downloads new documents from S3 (or reads from data/raw/ in local mode) "
            "and indexes them into the vector database. Already-indexed files are skipped "
            "automatically — safe to run at any time."
        )

        st.divider()

        # ── Options ───────────────────────────────────────────────────────────
        col_folder, col_force = st.columns([2, 1])

        with col_folder:
            folder_options = ["All folders"] + KB_SUBFOLDERS
            selected_folder = st.selectbox(
                "Folder to ingest",
                options=folder_options,
                help="Choose a specific subfolder to ingest, or run all folders at once.",
            )

        with col_force:
            st.write("")   # vertical alignment spacer
            force_reindex = st.checkbox(
                "Force re-index",
                value=False,
                help="Re-index all files even if already in the database. "
                     "Use after replacing a document with an updated version.",
            )

        # ── Run button ────────────────────────────────────────────────────────
        run_col, _ = st.columns([1, 2])
        with run_col:
            run_clicked = st.button(
                "▶ Run Ingestion",
                type="primary",
                use_container_width=True,
            )

        if run_clicked:
            # Server-side validation: confirm selected_folder is in the known
            # allow-list before passing it to the subprocess.  The UI selectbox
            # already limits the choices, but defence-in-depth requires
            # validating on the server regardless of how the value arrived.
            if selected_folder != "All folders" and selected_folder not in KB_SUBFOLDERS:
                st.error(f"Invalid folder '{selected_folder}'. Must be one of the known KB subfolders.")
                st.stop()

            # Build command — same Python interpreter as the running app
            _project_root = Path(__file__).parent
            cmd = [sys.executable, "-X", "utf8",
                   str(_project_root / "scripts" / "run_ingestion.py")]

            if selected_folder != "All folders":
                cmd += ["--folder", selected_folder]
            if force_reindex:
                cmd += ["--force"]

            log_event(
                "admin_action",
                username=current_user["username"],
                detail=f"ingestion started: folder={selected_folder} force={force_reindex}",
            )

            # Stream output line-by-line into the UI
            with st.status("⏳ Ingestion running...", expanded=True) as _status:
                _output_area = st.empty()
                _output_text = ""

                try:
                    _env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
                    _proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        cwd=str(_project_root),
                        env=_env,
                    )

                    for _line in iter(_proc.stdout.readline, b""):
                        _output_text += _line.decode("utf-8", errors="replace")
                        _output_area.code(_output_text, language="text")

                    _proc.wait()

                    if _proc.returncode == 0:
                        _status.update(label="✅ Ingestion complete!", state="complete")
                        log_event(
                            "admin_action",
                            username=current_user["username"],
                            detail=f"ingestion finished successfully: folder={selected_folder}",
                        )
                        # Bust the KB stats cache so the sidebar reflects new counts
                        get_stats.clear()
                    else:
                        _status.update(label="❌ Ingestion failed — see output above.", state="error")
                        log_event(
                            "admin_action",
                            username=current_user["username"],
                            detail=f"ingestion failed (exit {_proc.returncode}): folder={selected_folder}",
                        )

                except Exception as _exc:
                    _status.update(label=f"❌ Error: {_exc}", state="error")

        # ── Current KB stats (refreshes on each page load) ───────────────────
        st.divider()
        st.subheader("Current Knowledge Base")

        _kb_stats = _store.stats()
        _s1, _s2 = st.columns(2)
        _s1.metric("Total indexed chunks", _kb_stats["total_chunks"])
        _s2.metric("SSCP priority chunks", _kb_stats.get("sscp_chunks", 0))

        if _kb_stats.get("by_domain"):
            st.caption("**Chunks by domain folder**")
            _domain_cols = st.columns(4)
            for _i, (_dom, _cnt) in enumerate(sorted(_kb_stats["by_domain"].items())):
                _domain_cols[_i % 4].metric(_dom, _cnt)

        if _kb_stats["total_chunks"] == 0:
            st.info(
                "The knowledge base is empty. "
                "Upload documents to S3 (or data/raw/ in local mode) then click **▶ Run Ingestion**."
            )
