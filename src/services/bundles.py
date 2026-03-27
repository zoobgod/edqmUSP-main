"""Shared bundle and file packaging helpers.

These helpers are frontend-agnostic and safe to reuse from Streamlit/FastAPI.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path


def safe_file_part(value: str) -> str:
    """Sanitize file name parts for safe ZIP and download names."""
    sanitized = re.sub(r'[\\/*?:"<>|]+', "_", (value or "").strip()).strip(".")
    return sanitized or "position"


def mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def bundle_name(source: str, code: str, position_name: str) -> str:
    return f"{source.upper()}_{code}_{position_name}".strip()


def zip_member_name(bundle: str, doc_type: str, file_path: Path) -> str:
    if doc_type == "COO":
        # Keep COO naming as source filename (country-derived PDF/TXT).
        return re.sub(r"_\d+(\.[^.]+)$", r"\1", file_path.name)

    suffix = file_path.suffix.lower() or ".pdf"
    return f"{safe_file_part(bundle)}_{doc_type}{suffix}"


def build_position_zip(bundle: str, files_by_doc: dict[str, Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for doc_type in ("COA", "MSDS", "COO"):
            file_path = files_by_doc.get(doc_type)
            if not file_path or not file_path.exists():
                continue
            archive.writestr(zip_member_name(bundle, doc_type, file_path), file_path.read_bytes())

    buffer.seek(0)
    return buffer.getvalue()


def build_batch_zip(
    source: str,
    successful_files: dict[str, dict[str, Path]],
    position_names: dict[str, str],
    manifest_text: str | None = None,
) -> bytes:
    """Build one batch ZIP with one folder per position; optional manifest at root."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for code, files_by_doc in successful_files.items():
            position = position_names.get(code, code)
            bundle = bundle_name(source, code, position)
            folder = safe_file_part(bundle)
            for doc_type in ("COA", "MSDS", "COO"):
                file_path = files_by_doc.get(doc_type)
                if not file_path or not file_path.exists():
                    continue
                archive.writestr(f"{folder}/{zip_member_name(bundle, doc_type, file_path)}", file_path.read_bytes())

        if manifest_text:
            archive.writestr("manifest.txt", manifest_text)

    buffer.seek(0)
    return buffer.getvalue()


def resolve_position_name(downloader, code: str) -> str:
    getter = getattr(downloader, "get_position_name", None)
    if callable(getter):
        try:
            name = (getter(code) or "").strip()
            if name:
                return name
        except Exception:
            return code
    return code
