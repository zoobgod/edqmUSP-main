import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _read_token_file() -> str:
    """Read YDisk token from ydisk_token.txt as fallback."""
    token_file = BASE_DIR / "ydisk_token.txt"
    if token_file.exists():
        for line in token_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


# Yandex Disk
YDISK_TOKEN = os.getenv("YDISK_TOKEN") or _read_token_file()
YDISK_UPLOAD_PATH = os.getenv("YDISK_UPLOAD_PATH", "/edqmUSP")

# EDQM
EDQM_USERNAME = os.getenv("EDQM_USERNAME", "")
EDQM_PASSWORD = os.getenv("EDQM_PASSWORD", "")

# USP
USP_USERNAME = os.getenv("USP_USERNAME", "")
USP_PASSWORD = os.getenv("USP_PASSWORD", "")

# Local
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(BASE_DIR / "downloads")))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Browser
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
