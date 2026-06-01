"""
storage_adapter.py — Abstracts document source: local filesystem or AWS S3.

Set STORAGE_BACKEND=local (default) or STORAGE_BACKEND=s3 in .env.

S3 env vars (only required when STORAGE_BACKEND=s3):
  AWS_BUCKET_NAME   — bucket containing your documents
  AWS_PREFIX        — folder prefix inside the bucket (default: "documents/")
  AWS_REGION        — AWS region (default: "ap-southeast-2")

Full S3 bucket structure (mirrors local data/raw/):
  documents/                  ← general KB documents
      who_guidelines/
      standards_docs/
      research_papers/
      donor_guidelines/
      case_studies/
      country_profiles/
      open_source_tools/
      sscp/                   ← SSCP priority documents
      to_be_reviewed/         ← submitted documents awaiting review (backed up here)
      fetched/                ← web pages fetched from urls.txt (backed up here)

The sscp/ subfolder structure is preserved when downloading from S3 so that
SSCP priority tagging works identically to local mode.

boto3 credentials follow the standard AWS chain:
  IAM role (recommended on EC2/ECS) → env vars → ~/.aws/credentials
"""

import os
import tempfile
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


# ── S3 backup helpers — used by kb_submissions.py and web_fetcher.py ─────────
# These functions back up files to S3 for safety. They are no-ops in local mode.
# All S3 errors are caught and logged as warnings — backup failure never blocks
# the primary operation (saving/serving files locally still works).

def is_s3_mode() -> bool:
    """Return True if STORAGE_BACKEND=s3 is configured."""
    return os.getenv("STORAGE_BACKEND", "local").lower() == "s3"


def _get_s3_client():
    """Return a boto3 S3 client using configured region. Raises on import/config error."""
    try:
        import boto3
    except ImportError:
        raise ImportError("boto3 is required for S3. Install it: pip install boto3")
    region = os.getenv("AWS_REGION", "ap-southeast-2")
    return boto3.client("s3", region_name=region)


def _get_s3_config() -> tuple[str, str]:
    """Return (bucket, prefix). Raises ValueError if bucket not set."""
    bucket = os.environ.get("AWS_BUCKET_NAME", "")
    if not bucket:
        raise ValueError("AWS_BUCKET_NAME must be set in .env when STORAGE_BACKEND=s3")
    prefix = os.getenv("AWS_PREFIX", "documents/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return bucket, prefix


def s3_upload_file(local_path: Path, relative_key: str) -> bool:
    """
    Upload a local file to S3 at {prefix}{relative_key}.

    Example:
        s3_upload_file(Path("data/raw/to_be_reviewed/abc_file.pdf"),
                       "to_be_reviewed/abc_file.pdf")
        → uploads to s3://bucket/documents/to_be_reviewed/abc_file.pdf

    Returns True on success, False on failure (logs a warning, never raises).
    No-op if STORAGE_BACKEND != s3.
    """
    if not is_s3_mode():
        return True  # silently succeed in local mode

    try:
        s3 = _get_s3_client()
        bucket, prefix = _get_s3_config()
        key = f"{prefix}{relative_key}"
        s3.upload_file(str(local_path), bucket, key)
        print(f"  [S3 backup] Uploaded: s3://{bucket}/{key}")
        return True
    except Exception as e:
        print(f"  [S3 backup] WARNING — upload failed (local file is safe): {e}")
        return False


def s3_move_file(src_relative_key: str, dest_relative_key: str) -> bool:
    """
    Move a file within S3 by copying to new key then deleting the source.

    Example:
        s3_move_file("to_be_reviewed/abc_file.pdf",
                     "who_guidelines/abc_file.pdf")

    Returns True on success, False on failure. No-op if not s3 mode.
    """
    if not is_s3_mode():
        return True

    try:
        s3 = _get_s3_client()
        bucket, prefix = _get_s3_config()
        src_key = f"{prefix}{src_relative_key}"
        dest_key = f"{prefix}{dest_relative_key}"

        # Copy to new location
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": src_key},
            Key=dest_key,
        )
        # Delete original
        s3.delete_object(Bucket=bucket, Key=src_key)
        print(f"  [S3] Moved: {src_key} → {dest_key}")
        return True
    except Exception as e:
        print(f"  [S3] WARNING — move failed: {e}")
        return False


def s3_delete_file(relative_key: str) -> bool:
    """
    Delete a file from S3. No-op in local mode.
    Used when a submission is rejected and the file should be cleaned up.
    """
    if not is_s3_mode():
        return True

    try:
        s3 = _get_s3_client()
        bucket, prefix = _get_s3_config()
        key = f"{prefix}{relative_key}"
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"  [S3] Deleted: {key}")
        return True
    except Exception as e:
        print(f"  [S3] WARNING — delete failed: {e}")
        return False


class StorageAdapter:
    def __init__(self):
        self.backend = os.getenv("STORAGE_BACKEND", "local").lower()
        self._tmp_dir: Path | None = None  # persists for lifetime of this process

    def get_document_root(self, local_dir: str = "./data/raw") -> Path:
        """
        Return the root directory containing documents to ingest.

        - local: returns Path(local_dir) directly — no download needed.
        - s3:    downloads all documents from S3 into a temp directory,
                 preserving the sscp/ subfolder structure, and returns
                 that temp directory.

        The temp directory (S3 mode) persists for the lifetime of this
        process — subsequent calls return the same path without re-downloading.
        """
        if self.backend == "s3":
            if self._tmp_dir is None:
                self._tmp_dir = self._download_from_s3()
            return self._tmp_dir
        return Path(local_dir)

    # ── Local ─────────────────────────────────────────────────────────────────

    def list_documents(self, local_dir: str = "./data/raw") -> list[Path]:
        """
        Legacy helper — returns a flat list of all ingestible documents.
        Prefer get_document_root() for new code so subfolder structure is preserved.
        """
        root = self.get_document_root(local_dir)
        if not root.exists():
            return []
        return [f for f in root.rglob("*") if f.suffix.lower() in SUPPORTED_EXTENSIONS]

    # ── S3 ────────────────────────────────────────────────────────────────────

    def _download_from_s3(self) -> Path:
        """
        Download all documents from S3 to a local temp directory.

        Preserves the relative subfolder structure under AWS_PREFIX so that
        documents/sscp/file.pdf  →  tmp_dir/sscp/file.pdf

        This means the existing SSCP detection logic (path.parent.name == "sscp")
        works identically to local mode.
        """
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 storage. Install it: pip install boto3"
            )

        bucket = os.environ.get("AWS_BUCKET_NAME")
        if not bucket:
            raise ValueError(
                "AWS_BUCKET_NAME must be set in .env when STORAGE_BACKEND=s3"
            )

        prefix = os.getenv("AWS_PREFIX", "documents/")
        # Ensure prefix ends with /
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        region = os.getenv("AWS_REGION", "ap-southeast-2")

        print(f"Downloading documents from s3://{bucket}/{prefix} ...")

        s3 = boto3.client("s3", region_name=region)
        tmp_dir = Path(tempfile.mkdtemp(prefix="siagent_s3_"))

        paginator = s3.get_paginator("list_objects_v2")
        downloaded = 0
        skipped = 0

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]  # e.g. "documents/sscp/file.pdf"
                suffix = Path(key).suffix.lower()

                if suffix not in SUPPORTED_EXTENSIONS:
                    skipped += 1
                    continue

                # Strip the prefix to get the relative path
                # "documents/sscp/file.pdf" with prefix "documents/" → "sscp/file.pdf"
                relative = key[len(prefix):]  # e.g. "sscp/file.pdf" or "file.pdf"

                if not relative:  # skip the prefix key itself if it exists as an object
                    continue

                local_path = tmp_dir / relative
                local_path.parent.mkdir(parents=True, exist_ok=True)

                print(f"  Downloading: {relative}")
                s3.download_file(bucket, key, str(local_path))
                downloaded += 1

        print(f"Downloaded {downloaded} documents from S3 ({skipped} non-document files skipped)")
        print(f"Local temp directory: {tmp_dir}")

        return tmp_dir
