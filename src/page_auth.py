"""
page_auth.py — Shared authentication check for Streamlit multipage apps.

Every page in pages/ calls require_login() at the top. If the user is not
logged in (session state has no current_user), they see a prompt to go back
to the main page and log in first.

Roles:
    admin    — full access everywhere
    reviewer — chat + document review (KB Review page)
    user     — chat only
"""

import streamlit as st


def require_login(allowed_roles: list[str] | None = None) -> dict:
    """
    Verify the user is logged in with an appropriate role.

    Args:
        allowed_roles: List of roles that may access this page.
                       None means any authenticated user is allowed.

    Returns:
        current_user dict {username, role, name} if access is granted.
        Calls st.stop() otherwise — the rest of the page does not render.
    """
    if not st.session_state.get("logged_in"):
        st.warning("You need to be logged in to access this page.")
        st.page_link("app.py", label="← Go to login", icon="🔐")
        st.stop()

    current_user = st.session_state.get("current_user", {})
    role = current_user.get("role", "")

    if allowed_roles and role not in allowed_roles:
        st.error(f"This page requires one of these roles: {', '.join(allowed_roles)}")
        st.page_link("app.py", label="← Back to chat", icon="💬")
        st.stop()

    return current_user


def is_reviewer_or_admin(role: str) -> bool:
    """Return True if the role can access review functionality."""
    return role in ("admin", "reviewer")
