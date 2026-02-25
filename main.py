"""CLI entry point for edqmUSP.

Usage:
    python main.py edqm Y0001532 Y0001234
    python main.py usp 1134357
    python main.py upload
    python main.py upload edqm
"""

import logging
import sys

from src.config import DOWNLOAD_DIR
from src.downloaders.edqm import EDQMDownloader
from src.downloaders.usp import USPDownloader
from src.uploaders.ydisk import YDiskUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_edqm(codes: list[str]):
    """Download documents from EDQM."""
    with EDQMDownloader() as dl:
        for code in codes:
            logger.info("Processing EDQM product: %s", code)
            results = dl.download_all(code)
            for r in results:
                status = "OK" if r.success else f"FAIL ({r.error})"
                logger.info("  %s: %s", r.doc_type, status)


def cmd_usp(codes: list[str]):
    """Download documents from USP."""
    with USPDownloader() as dl:
        for code in codes:
            logger.info("Processing USP product: %s", code)
            results = dl.download_all(code)
            for r in results:
                status = "OK" if r.success else f"FAIL ({r.error})"
                logger.info("  %s: %s", r.doc_type, status)


def cmd_upload(source: str = "all"):
    """Upload downloaded files to Yandex Disk."""
    uploader = YDiskUploader()
    if not uploader.connect():
        logger.error("Failed to connect to Yandex Disk")
        sys.exit(1)

    sources = []
    if source in ("all", "edqm"):
        sources.append(("edqm", DOWNLOAD_DIR / "edqm"))
    if source in ("all", "usp"):
        sources.append(("usp", DOWNLOAD_DIR / "usp"))

    for subfolder, dir_path in sources:
        if not dir_path.exists():
            logger.info("No %s downloads directory", subfolder.upper())
            continue
        results = uploader.upload_directory(dir_path, subfolder)
        for fname, success in results.items():
            status = "OK" if success else "FAIL"
            logger.info("  %s: %s", fname, status)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "edqm":
        codes = sys.argv[2:]
        if not codes:
            print("Usage: python main.py edqm <code1> [code2] ...")
            sys.exit(1)
        cmd_edqm(codes)

    elif command == "usp":
        codes = sys.argv[2:]
        if not codes:
            print("Usage: python main.py usp <code1> [code2] ...")
            sys.exit(1)
        cmd_usp(codes)

    elif command == "upload":
        source = sys.argv[2] if len(sys.argv) > 2 else "all"
        cmd_upload(source)

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
