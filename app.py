"""Streamlit UI for edqmUSP - public document download + YDisk upload."""

import io
import logging
import re
import zipfile
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

    downloader_cls = EDQMDownloader if source == "edqm" else USPDownloader
    downloader = downloader_cls(download_dir=base_dir)
    downloader.start()

    try:
        total = max(1, len(codes) * len(doc_types))
        done = 0

        for code in codes:
            status.info(f"Searching for {code}...")
            if downloader.search_product(code):
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
            else:
                for doc in doc_types:
                    done += 1
                    progress.progress(done / total)
                    with results_container:
                        st.error(f"{code} {doc}: Product not found")

        status.success(f"{source.upper()} downloads complete!")

        if successful_files:
            with download_container:
                st.markdown("### Download to your PC")
                for code in codes:
                    files_by_doc = successful_files.get(code, {})
                    if not files_by_doc:
                        continue

                    st.markdown(f"**{code}**")
                    cols = st.columns(4)
                    col_idx = 0

                    for doc in doc_types:
                        file_path = files_by_doc.get(doc)
                        if not file_path or not file_path.exists():
                            continue

                        data = file_path.read_bytes()
                        mime = _mime_type_for(file_path)
                        with cols[col_idx % 4]:
                            st.download_button(
                                label=f"{doc}",
                                data=data,
                                file_name=file_path.name,
                                mime=mime,
                                key=f"dl-{source}-{code}-{doc}",
                            )
                        col_idx += 1

                    zip_data = _build_zip_for_position(code, files_by_doc)
                    with cols[col_idx % 4]:
                        st.download_button(
                            label="ZIP",
                            data=zip_data,
                            file_name=f"{_safe_file_part(code)}.zip",
                            mime="application/zip",
                            key=f"zip-{source}-{code}",
                        )
    finally:
        downloader.stop()


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


def _zip_member_name(position: str, doc_type: str, file_path: Path) -> str:
    if doc_type == "COO":
        # Keep COO naming as country name (.txt).
        return file_path.name

    suffix = file_path.suffix.lower() or ".pdf"
    return f"{_safe_file_part(position)}_{doc_type}{suffix}"


def _build_zip_for_position(position: str, files_by_doc: dict[str, Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for doc_type in ("COA", "MSDS", "COO"):
            file_path = files_by_doc.get(doc_type)
            if not file_path or not file_path.exists():
                continue
            archive.writestr(_zip_member_name(position, doc_type, file_path), file_path.read_bytes())

    buffer.seek(0)
    return buffer.getvalue()


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

                    files = list(dir_path.iterdir())
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

    for source in ["edqm", "usp"]:
        source_dir = dl_path / source
        if source_dir.exists():
            files = sorted(source_dir.iterdir())
            if files:
                st.markdown(f"**{source.upper()}** ({len(files)} files)")
                for f in files:
                    size_kb = f.stat().st_size / 1024
                    st.text(f"  {f.name} ({size_kb:.1f} KB)")
            else:
                st.info(f"No {source.upper()} files downloaded yet.")
        else:
            st.info(f"No {source.upper()} download directory yet.")
