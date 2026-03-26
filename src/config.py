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

# EDQM and USP downloads are public; no credentials needed.

# Local
def _resolve_download_dir(create: bool = True) -> Path:
    preferred = Path(os.getenv("DOWNLOAD_DIR", str(BASE_DIR / "downloads")))
    if not create:
        return preferred

    candidates = [preferred]

    # Vercel/serverless runtimes are typically writable only under /tmp.
    tmp_fallback = Path("/tmp/edqmUSP-downloads")
    if tmp_fallback not in candidates:
        candidates.append(tmp_fallback)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return preferred


DOWNLOAD_DIR = _resolve_download_dir(
    create=os.getenv("DOWNLOAD_DIR_CREATE_ON_IMPORT", "true").lower() == "true"
)

# Browser
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
