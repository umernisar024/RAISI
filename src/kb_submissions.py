"""
kb_submissions.py — Document submission workflow for the knowledge base.

Tracks documents submitted by users for review before they are ingested.
Submitted files land in data/raw/to_be_reviewed/ and are moved to the
appropriate KB subfolder by an admin or reviewer after review.

The ingest script explicitly skips to_be_reviewed/ so unapproved content
never enters the knowledge base.
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.storage_adapter import (
    s3_upload_file, s3_move_file, s3_delete_file, is_s3_mode,
    _get_s3_client, _get_s3_config,
)

# ── KB folder definitions ─────────────────────────────────────────────────────
# Order controls dropdown display. Add new folders here only — do not rename
# existing ones without re-ingesting the KB (domain metadata would break).

KB_SUBFOLDERS = [
    "who_guidelines",
    "standards_docs",
    "research_papers",
    "donor_guidelines",
    "case_studies",
    "country_profiles",
    "open_source_tools",
    "sscp",
]

# Staging folder — documents here are NOT ingested until reviewed and moved
STAGING_FOLDER = "to_be_reviewed"

# All KB folders including staging
ALL_FOLDERS = KB_SUBFOLDERS + [STAGING_FOLDER]

# Human-readable labels for UI dropdowns
KB_FOLDER_LABELS: dict[str, str] = {
    "who_guidelines":   "WHO Guidelines",
    "standards_docs":   "Standards & Specifications",
    "research_papers":  "Research Papers",
    "donor_guidelines": "Donor & Partner Guidelines",
    "case_studies":     "Case Studies & Pilots",
    "country_profiles": "Country Profiles",
    "open_source_tools":"Open Source Tools & Platforms",
    "sscp":             "SSCP (Priority Sources)",
    "to_be_reviewed":   "To Be Reviewed",
}

RAW_DIR = Path("data/raw")
SUBMISSIONS_FILE = Path("data/submissions.json")
SUPPORTED_UPLOAD_TYPES = [".pdf", ".docx", ".txt", ".md"]
MAX_UPLOAD_MB = 50


# ── Directory helpers ─────────────────────────────────────────────────────────

def ensure_kb_dirs() -> None:
    """Create all KB subdirectories if they don't exist."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for folder in ALL_FOLDERS:
        (RAW_DIR / folder).mkdir(exist_ok=True)


# ── Submission metadata ───────────────────────────────────────────────────────

def _load_submissions() -> list[dict]:
    if not SUBMISSIONS_FILE.exists():
        # Attempt to restore from S3 if in s3 mode
        _s3_restore_submissions()
    if not SUBMISSIONS_FILE.exists():
        return []
    try:
        return json.loads(SUBMISSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_submissions(submissions: list[dict]) -> None:
    SUBMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBMISSIONS_FILE.write_text(
        json.dumps(submissions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _s3_backup_submissions()


def _s3_backup_submissions() -> None:
    """Back up submissions.json to S3. No-op in local mode."""
    if not is_s3_mode():
        return
    try:
        s3 = _get_s3_client()
        bucket, prefix = _get_s3_config()
        key = f"{prefix}submissions.json"
        s3.upload_file(str(SUBMISSIONS_FILE), bucket, key)
    except Exception as e:
        print(f"  [S3 backup] WARNING — submissions.json backup failed: {e}")


def _s3_restore_submissions() -> None:
    """Restore submissions.json from S3 if local file is missing. No-op in local mode."""
    if not is_s3_mode():
        return
    try:
        s3 = _get_s3_client()
        bucket, prefix = _get_s3_config()
        key = f"{prefix}submissions.json"
        SUBMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(SUBMISSIONS_FILE))
        print(f"  [S3] Restored submissions.json from s3://{bucket}/{key}")
    except Exception:
        pass  # File doesn't exist in S3 yet — normal for first run


def get_pending_submissions() -> list[dict]:
    """Return all submissions with status 'pending'."""
    return [s for s in _load_submissions() if s.get("status") == "pending"]


def get_all_submissions() -> list[dict]:
    """Return all submissions (pending + reviewed)."""
    return _load_submissions()


def save_submission(
    file_bytes: bytes,
    original_filename: str,
    content_name: str,
    description: str,
    url: str,
    category: str,
    submitted_by: str,
) -> dict:
    """
    Save an uploaded file to the to_be_reviewed/ staging folder and
    record its metadata. Returns the submission record.
    """
    ensure_kb_dirs()

    # Generate unique ID to avoid filename collisions
    submission_id = str(uuid.uuid4())[:8]
    safe_name = "".join(c for c in original_filename if c.isalnum() or c in "._- ")
    stored_filename = f"{submission_id}_{safe_name}"
    dest_path = RAW_DIR / STAGING_FOLDER / stored_filename

    dest_path.write_bytes(file_bytes)

    # Back up to S3 immediately (no-op in local mode)
    # This protects against EBS loss before the document is reviewed
    if file_bytes:
        s3_upload_file(dest_path, f"{STAGING_FOLDER}/{stored_filename}")

    record = {
        "id": submission_id,
        "stored_filename": stored_filename,
        "original_filename": original_filename,
        "content_name": content_name,
        "description": description,
        "url": url,
        "category": category,
        "submitted_by": submitted_by,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "review_comment": "",
        "reviewed_by": "",
        "reviewed_at": "",
        "moved_to": "",
    }

    submissions = _load_submissions()
    submissions.append(record)
    _save_submissions(submissions)

    return record


def move_to_kb(
    submission_id: str,
    target_folder: str,
    review_comment: str,
    reviewed_by: str,
) -> tuple[bool, str]:
    """
    Move a submission from to_be_reviewed/ to the chosen KB subfolder.
    Updates the metadata record. Does NOT trigger ingestion.

    Returns (success, message).
    """
    submissions = _load_submissions()
    record = next((s for s in submissions if s["id"] == submission_id), None)

    if not record:
        return False, f"Submission {submission_id} not found."

    if record["status"] != "pending":
        return False, "This submission has already been reviewed."

    src_path = RAW_DIR / STAGING_FOLDER / record["stored_filename"]
    if not src_path.exists():
        return False, f"File not found on disk: {record['stored_filename']}"

    dest_dir = RAW_DIR / target_folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / record["stored_filename"]

    try:
        shutil.move(str(src_path), str(dest_path))
    except Exception as e:
        return False, f"Failed to move file: {e}"

    # Mirror the move in S3 (no-op in local mode)
    s3_move_file(
        src_relative_key=f"{STAGING_FOLDER}/{record['stored_filename']}",
        dest_relative_key=f"{target_folder}/{record['stored_filename']}",
    )

    # Update record
    record["status"] = "approved"
    record["review_comment"] = review_comment
    record["reviewed_by"] = reviewed_by
    record["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    record["moved_to"] = target_folder

    _save_submissions(submissions)
    return True, f"Moved to {KB_FOLDER_LABELS.get(target_folder, target_folder)}. Run ingestion to index it."


def reject_submission(
    submission_id: str,
    review_comment: str,
    reviewed_by: str,
) -> tuple[bool, str]:
    """
    Reject a submission — marks it rejected but leaves the file in staging.
    The file can be deleted manually or cleaned up later.

    Returns (success, message).
    """
    submissions = _load_submissions()
    record = next((s for s in submissions if s["id"] == submission_id), None)

    if not record:
        return False, f"Submission {submission_id} not found."

    record["status"] = "rejected"
    record["review_comment"] = review_comment
    record["reviewed_by"] = reviewed_by
    record["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    # Remove from S3 staging on rejection (no-op in local mode)
    s3_delete_file(f"{STAGING_FOLDER}/{record['stored_filename']}")

    _save_submissions(submissions)
    return True, "Submission rejected."


def get_submission_file_path(submission_id: str) -> Path | None:
    """Return the on-disk path for a submission's file, or None if not found."""
    submissions = _load_submissions()
    record = next((s for s in submissions if s["id"] == submission_id), None)
    if not record:
        return None

    if record.get("moved_to"):
        path = RAW_DIR / record["moved_to"] / record["stored_filename"]
    else:
        path = RAW_DIR / STAGING_FOLDER / record["stored_filename"]

    return path if path.exists() else None
