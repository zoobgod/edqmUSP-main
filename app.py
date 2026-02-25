"""Streamlit UI for edqmUSP - Download & Upload COA/MSDS/COO documents."""

import logging
import streamlit as st
from pathlib import Path

from src.config import (
    YDISK_TOKEN, EDQM_USERNAME, EDQM_PASSWORD,
    USP_USERNAME, USP_PASSWORD, DOWNLOAD_DIR,
)
from src.downloaders.edqm import EDQMDownloader
from src.downloaders.usp import USPDownloader
from src.uploaders.ydisk import YDiskUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

st.set_page_config(page_title="edqmUSP", page_icon="📄", layout="wide")
st.title("edqmUSP - Document Downloader & Uploader")
st.caption("Download COA, MSDS and COO from EDQM and USP, then upload to Yandex Disk.")

# --- Sidebar: Configuration ---
with st.sidebar:
    st.header("Configuration")

    st.subheader("EDQM Credentials")
    edqm_user = st.text_input("EDQM Username", value=EDQM_USERNAME, type="default")
    edqm_pass = st.text_input("EDQM Password", value=EDQM_PASSWORD, type="password")

    st.subheader("USP Credentials")
    usp_user = st.text_input("USP Username", value=USP_USERNAME, type="default")
    usp_pass = st.text_input("USP Password", value=USP_PASSWORD, type="password")

    st.subheader("Yandex Disk")
    ydisk_token = st.text_input("YDisk Token", value=YDISK_TOKEN, type="password")
    ydisk_connected = False
    if ydisk_token:
        if st.button("Test YDisk Connection"):
            uploader = YDiskUploader(token=ydisk_token)
            if uploader.connect():
                st.success("Connected to Yandex Disk")
                ydisk_connected = True
            else:
                st.error("Failed to connect. Check your token.")

    st.subheader("Settings")
    headless = st.checkbox("Headless browser", value=True)
    download_dir = st.text_input("Download directory", value=str(DOWNLOAD_DIR))

# --- Main Area: Tabs ---
tab_edqm, tab_usp, tab_upload, tab_status = st.tabs(["EDQM Download", "USP Download", "Upload to YDisk", "Downloaded Files"])

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
        elif not edqm_user or not edqm_pass:
            st.warning("Enter EDQM credentials in the sidebar.")
        else:
            progress = st.progress(0)
            status = st.empty()
            results_container = st.container()

            dl = EDQMDownloader(
                username=edqm_user,
                password=edqm_pass,
                download_dir=Path(download_dir),
                headless=headless,
            )
            dl.start()

            try:
                status.info("Logging in to EDQM...")
                if not dl.login():
                    st.error("EDQM login failed. Check credentials.")
                else:
                    total = len(codes) * len(edqm_doc_types)
                    done = 0
                    for code in codes:
                        status.info(f"Searching for {code}...")
                        if dl.search_product(code):
                            for doc in edqm_doc_types:
                                status.info(f"Downloading {doc} for {code}...")
                                result = dl.download_document(code, doc)
                                done += 1
                                progress.progress(done / total)
                                with results_container:
                                    if result.success:
                                        st.success(f"{code} {doc}: {result.file_path}")
                                    else:
                                        st.error(f"{code} {doc}: {result.error}")
                                dl._driver.back()
                        else:
                            for doc in edqm_doc_types:
                                done += 1
                                progress.progress(done / total)
                                with results_container:
                                    st.error(f"{code} {doc}: Product not found")

                    status.success("EDQM downloads complete!")
            finally:
                dl.stop()

# --- USP Tab ---
with tab_usp:
    st.subheader("Download from USP")
    usp_codes = st.text_area(
        "Enter USP catalogue numbers (one per line)",
        placeholder="1134357\n1234567",
        height=150,
    )
    usp_doc_types = st.multiselect(
        "Document types", ["COA", "MSDS"], default=["COA", "MSDS"],
        key="usp_doc_types",
    )

    if st.button("Download from USP", type="primary"):
        codes = [c.strip() for c in usp_codes.strip().splitlines() if c.strip()]
        if not codes:
            st.warning("Enter at least one catalogue number.")
        elif not usp_user or not usp_pass:
            st.warning("Enter USP credentials in the sidebar.")
        else:
            progress = st.progress(0)
            status = st.empty()
            results_container = st.container()

            dl = USPDownloader(
                username=usp_user,
                password=usp_pass,
                download_dir=Path(download_dir),
                headless=headless,
            )
            dl.start()

            try:
                status.info("Logging in to USP...")
                if not dl.login():
                    st.error("USP login failed. Check credentials.")
                else:
                    total = len(codes) * len(usp_doc_types)
                    done = 0
                    for code in codes:
                        status.info(f"Searching for {code}...")
                        if dl.search_product(code):
                            for doc in usp_doc_types:
                                status.info(f"Downloading {doc} for {code}...")
                                result = dl.download_document(code, doc)
                                done += 1
                                progress.progress(done / total)
                                with results_container:
                                    if result.success:
                                        st.success(f"{code} {doc}: {result.file_path}")
                                    else:
                                        st.error(f"{code} {doc}: {result.error}")
                        else:
                            for doc in usp_doc_types:
                                done += 1
                                progress.progress(done / total)
                                with results_container:
                                    st.error(f"{code} {doc}: Product not found")

                    status.success("USP downloads complete!")
            finally:
                dl.stop()

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
                    dirs_to_upload = [
                        ("edqm", dl_path / "edqm"),
                        ("usp", dl_path / "usp"),
                    ]

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
