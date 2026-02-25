"""Streamlit UI for edqmUSP - public document download + YDisk upload."""

import logging
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
                        else:
                            st.error(f"{code} {doc}: {result.error}")
            else:
                for doc in doc_types:
                    done += 1
                    progress.progress(done / total)
                    with results_container:
                        st.error(f"{code} {doc}: Product not found")

        status.success(f"{source.upper()} downloads complete!")
    finally:
        downloader.stop()


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
