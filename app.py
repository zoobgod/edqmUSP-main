"""Streamlit UI for edqmUSP - public document download + YDisk upload."""

import io
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.config import DOWNLOAD_DIR, YDISK_TOKEN
from src.downloaders.edqm import EDQMDownloader
from src.downloaders.usp import USPDownloader
from src.uploaders.ydisk import YDiskUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

st.set_page_config(page_title="edqmUSP", page_icon="📄", layout="wide")
st.title("edqmUSP - Document Downloader & Uploader")
st.caption(
    "Download COA, MSDS and COO from EDQM/USP public pages, then upload to Yandex Disk."
)


def _init_state():
    st.session_state.setdefault("download_batches", [])
    st.session_state.setdefault("download_batch_counter", 0)


_init_state()

with st.sidebar:
    st.header("Configuration")

    st.info("EDQM and USP downloads use public URLs. Login credentials are not required.")

    st.subheader("Yandex Disk")
    ydisk_token = st.text_input("YDisk Token", value=YDISK_TOKEN, type="password")
    if ydisk_token and st.button("Test YDisk Connection"):
        uploader = YDiskUploader(token=ydisk_token)
        if uploader.connect():
            st.success("Connected to Yandex Disk")
        else:
            st.error("Failed to connect. Check your token.")

    st.subheader("Settings")
    download_dir = st.text_input("Download directory", value=str(DOWNLOAD_DIR))


def _download_documents(source: str, codes: list[str], doc_types: list[str], base_dir: Path):
    progress = st.progress(0)
    status = st.empty()
    results_container = st.container()
    download_container = st.container()

    successful_files: dict[str, dict[str, Path]] = {}
    position_names: dict[str, str] = {}
    batch_started_at = datetime.now()
    batch_id = _next_batch_id()

    downloader_cls = EDQMDownloader if source == "edqm" else USPDownloader
    downloader = downloader_cls(download_dir=base_dir)
    downloader.start()

    try:
        total = max(1, len(codes) * len(doc_types))
        done = 0

        for code in codes:
            status.info(f"Searching for {code}...")
            if downloader.search_product(code):
                position_names[code] = _resolve_position_name(downloader, code)
                for doc in doc_types:
                    status.info(f"Downloading {doc} for {code}...")
                    result = downloader.download_document(code, doc)
                    done += 1
                    progress.progress(done / total)

                    with results_container:
                        if result.success:
                            st.success(f"{code} {doc}: {result.file_path}")
                            successful_files.setdefault(code, {})[doc] = Path(result.file_path)
                        else:
                            st.error(f"{code} {doc}: {result.error}")
                            if (
                                source == "edqm"
                                and doc == "MSDS"
                                and "Sigma SDS fallback failed" in result.error
                            ):
                                st.markdown(f"[Open Sigma SDS for {code}]({_sigma_sds_url(code)})")
            else:
                for doc in doc_types:
                    done += 1
                    progress.progress(done / total)
                    with results_container:
                        st.error(f"{code} {doc}: Product not found")

        status.success(f"{source.upper()} downloads complete!")

        if successful_files:
            _record_batch(batch_id, source, batch_started_at, successful_files, position_names)

            with download_container:
                st.markdown("### Download to your PC")
                batch_zip_data = _build_batch_zip(source, successful_files, position_names)
                st.download_button(
                    label="Download All (Nested ZIP)",
                    data=batch_zip_data,
                    file_name=f"{_safe_file_part(source.upper())}_BATCH_{batch_id}.zip",
                    mime="application/zip",
                    key=f"zip-batch-{source}-{batch_id}",
                )
                st.caption("Contains one ZIP per position bundle.")

                for code in codes:
                    files_by_doc = successful_files.get(code, {})
                    if not files_by_doc:
                        continue

                    position_name = position_names.get(code, code)
                    bundle_name = _bundle_name(source, code, position_name)
                    st.markdown(f"**{bundle_name}**")
                    st.caption(f"Catalogue: {code}")

                    cols = st.columns(5)
                    for idx, doc in enumerate(("COA", "MSDS", "COO")):
                        file_path = files_by_doc.get(doc)
                        if not file_path or not file_path.exists():
                            cols[idx].write(f"{doc}: -")
                            continue

                        data = file_path.read_bytes()
                        mime = _mime_type_for(file_path)
                        cols[idx].download_button(
                            label=doc,
                            data=data,
                            file_name=file_path.name,
                            mime=mime,
                            key=f"dl-{source}-{batch_id}-{code}-{doc}",
                        )

                    zip_data = _build_zip_for_position(bundle_name, files_by_doc)
                    cols[3].download_button(
                        label="Position ZIP",
                        data=zip_data,
                        file_name=f"{_safe_file_part(bundle_name)}.zip",
                        mime="application/zip",
                        key=f"zip-{source}-{batch_id}-{code}",
                    )
                    cols[4].write("")
    finally:
        downloader.stop()


def _resolve_position_name(downloader, code: str) -> str:
    getter = getattr(downloader, "get_position_name", None)
    if callable(getter):
        try:
            name = (getter(code) or "").strip()
            if name:
                return name
        except Exception as exc:  # pragma: no cover
            logging.warning("Could not resolve position name for %s: %s", code, exc)
    return code


def _safe_file_part(value: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]+', "_", (value or "").strip()).strip(".")
    return sanitized or "position"


def _mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _bundle_name(source: str, code: str, position_name: str) -> str:
    return f"{source.upper()}_{code}_{position_name}".strip()


def _zip_member_name(bundle_name: str, doc_type: str, file_path: Path) -> str:
    if doc_type == "COO":
        # Keep COO naming as country name (.txt).
        return file_path.name

    suffix = file_path.suffix.lower() or ".pdf"
    return f"{_safe_file_part(bundle_name)}_{doc_type}{suffix}"


def _build_zip_for_position(bundle_name: str, files_by_doc: dict[str, Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for doc_type in ("COA", "MSDS", "COO"):
            file_path = files_by_doc.get(doc_type)
            if not file_path or not file_path.exists():
                continue
            archive.writestr(_zip_member_name(bundle_name, doc_type, file_path), file_path.read_bytes())

    buffer.seek(0)
    return buffer.getvalue()


def _build_batch_zip(
    source: str,
    successful_files: dict[str, dict[str, Path]],
    position_names: dict[str, str],
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for code, files_by_doc in successful_files.items():
            position_name = position_names.get(code, code)
            bundle_name = _bundle_name(source, code, position_name)
            pos_zip = _build_zip_for_position(bundle_name, files_by_doc)
            archive.writestr(f"{_safe_file_part(bundle_name)}.zip", pos_zip)

    buffer.seek(0)
    return buffer.getvalue()


def _sigma_sds_url(code: str) -> str:
    safe_code = re.sub(r"[^a-z0-9]+", "", (code or "").lower())
    return f"https://www.sigmaaldrich.com/SE/en/sds/sial/{safe_code}?userType=anonymous"


def _next_batch_id() -> int:
    st.session_state["download_batch_counter"] += 1
    return int(st.session_state["download_batch_counter"])


def _record_batch(
    batch_id: int,
    source: str,
    started_at: datetime,
    successful_files: dict[str, dict[str, Path]],
    position_names: dict[str, str],
):
    positions = []
    for code, files_by_doc in successful_files.items():
        position_name = position_names.get(code, code)
        bundle_name = _bundle_name(source, code, position_name)
        file_entries = []

        for doc_type in ("COA", "MSDS", "COO"):
            path = files_by_doc.get(doc_type)
            if not path or not path.exists():
                continue

            stats = path.stat()
            file_entries.append(
                {
                    "doc_type": doc_type,
                    "file_name": path.name,
                    "file_path": str(path),
                    "size_kb": round(stats.st_size / 1024, 1),
                    "saved_at": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        if file_entries:
            positions.append(
                {
                    "code": code,
                    "position_name": position_name,
                    "bundle_name": bundle_name,
                    "files": file_entries,
                }
            )

    if not positions:
        return

    st.session_state["download_batches"].append(
        {
            "id": batch_id,
            "source": source.upper(),
            "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "positions": positions,
        }
    )


def _clear_download_cache(base_dir: Path):
    for source in ("edqm", "usp"):
        source_dir = base_dir / source
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

    st.session_state["download_batches"] = []
    st.session_state["download_batch_counter"] = 0


def _collect_download_file_rows(base_dir: Path) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for source in ("edqm", "usp"):
        source_dir = base_dir / source
        if not source_dir.exists():
            continue
        for file_path in sorted(source_dir.iterdir()):
            if not file_path.is_file():
                continue
            stats = file_path.stat()
            rows.append(
                {
                    "source": source.upper(),
                    "file_name": file_path.name,
                    "size_kb": round(stats.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "path": str(file_path),
                }
            )
    return rows


# --- Main Area: Tabs ---
tab_edqm, tab_usp, tab_upload, tab_status = st.tabs(
    ["EDQM Download", "USP Download", "Upload to YDisk", "Downloaded Files"]
)

# --- EDQM Tab ---
with tab_edqm:
    st.subheader("Download from EDQM")
    edqm_codes = st.text_area(
        "Enter EDQM product codes (one per line)",
        placeholder="Y0001532\nY0001234",
        height=150,
    )
    edqm_doc_types = st.multiselect(
        "Document types", ["COA", "MSDS", "COO"], default=["COA", "MSDS", "COO"]
    )

    if st.button("Download from EDQM", type="primary"):
        codes = [c.strip() for c in edqm_codes.strip().splitlines() if c.strip()]
        if not codes:
            st.warning("Enter at least one product code.")
        else:
            _download_documents("edqm", codes, edqm_doc_types, Path(download_dir))

# --- USP Tab ---
with tab_usp:
    st.subheader("Download from USP")
    usp_codes = st.text_area(
        "Enter USP catalogue numbers (one per line)",
        placeholder="1134357\n1234567",
        height=150,
    )
    usp_doc_types = st.multiselect(
        "Document types",
        ["COA", "MSDS", "COO"],
        default=["COA", "MSDS", "COO"],
        key="usp_doc_types",
    )

    if st.button("Download from USP", type="primary"):
        codes = [c.strip() for c in usp_codes.strip().splitlines() if c.strip()]
        if not codes:
            st.warning("Enter at least one catalogue number.")
        else:
            _download_documents("usp", codes, usp_doc_types, Path(download_dir))

# --- Upload Tab ---
with tab_upload:
    st.subheader("Upload to Yandex Disk")

    if not ydisk_token:
        st.warning("Configure your YDisk token in the sidebar first.")
    else:
        upload_source = st.radio(
            "Upload source",
            ["EDQM downloads", "USP downloads", "All downloads"],
        )

        if st.button("Upload to Yandex Disk", type="primary"):
            uploader = YDiskUploader(token=ydisk_token)
            if not uploader.connect():
                st.error("Failed to connect to Yandex Disk. Check your token.")
            else:
                dl_path = Path(download_dir)
                dirs_to_upload = []

                if upload_source == "EDQM downloads":
                    dirs_to_upload = [("edqm", dl_path / "edqm")]
                elif upload_source == "USP downloads":
                    dirs_to_upload = [("usp", dl_path / "usp")]
                else:
                    dirs_to_upload = [("edqm", dl_path / "edqm"), ("usp", dl_path / "usp")]

                for subfolder, dir_path in dirs_to_upload:
                    if not dir_path.exists():
                        st.info(f"No {subfolder.upper()} downloads found.")
                        continue

                    files = [p for p in dir_path.iterdir() if p.is_file()]
                    if not files:
                        st.info(f"No files in {subfolder.upper()} download folder.")
                        continue

                    st.info(f"Uploading {len(files)} files from {subfolder.upper()}...")
                    results = uploader.upload_directory(dir_path, subfolder)

                    for fname, success in results.items():
                        if success:
                            st.success(f"Uploaded: {fname}")
                        else:
                            st.error(f"Failed: {fname}")

                st.success("Upload complete!")

# --- Status Tab ---
with tab_status:
    st.subheader("Downloaded Files")
    dl_path = Path(download_dir)

    action_col1, action_col2 = st.columns([1, 3])
    with action_col1:
        if st.button("Clear Download Cache", type="secondary"):
            _clear_download_cache(dl_path)
            st.success("Download cache cleared.")
    with action_col2:
        st.caption("Removes all files from downloads/edqm and downloads/usp and resets batch history.")

    st.markdown("### Download Batches")
    batches = st.session_state.get("download_batches", [])
    if not batches:
        st.info("No download batches recorded in this session yet.")
    else:
        for batch in reversed(batches):
            title = f"Batch #{batch['id']} - {batch['source']} - {batch['started_at']}"
            with st.expander(title):
                for position in batch["positions"]:
                    st.markdown(f"**{position['bundle_name']}**")
                    st.caption(f"Catalogue: {position['code']}")
                    for item in position["files"]:
                        cols = st.columns([3, 1.5, 1.5, 1])
                        cols[0].write(item["file_name"])
                        cols[1].write(f"{item['size_kb']:.1f} KB")
                        cols[2].write(item["saved_at"])

                        path = Path(item["file_path"])
                        if path.exists():
                            cols[3].download_button(
                                "Download",
                                data=path.read_bytes(),
                                file_name=path.name,
                                mime=_mime_type_for(path),
                                key=f"status-dl-{batch['id']}-{position['code']}-{item['doc_type']}",
                            )
                        else:
                            cols[3].write("Missing")

    st.markdown("### All Files On Disk")
    file_rows = _collect_download_file_rows(dl_path)
    if file_rows:
        st.dataframe(file_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No files downloaded yet.")
