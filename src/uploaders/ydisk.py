"""Yandex Disk uploader module.

Uploads downloaded documents to Yandex Disk using the yadisk library.
Token is read from .env (YDISK_TOKEN) or ydisk_token.txt.
"""

import logging
from pathlib import Path

import yadisk

from src.config import YDISK_TOKEN, YDISK_UPLOAD_PATH

logger = logging.getLogger(__name__)


class YDiskUploader:
    def __init__(self, token: str = "", remote_path: str = ""):
        self.token = token or YDISK_TOKEN
        self.remote_path = remote_path or YDISK_UPLOAD_PATH
        self._client: yadisk.YaDisk | None = None

    def connect(self) -> bool:
        """Initialize the Yandex Disk client and verify the token."""
        if not self.token:
            logger.error("YDisk token not configured. Set YDISK_TOKEN in .env or ydisk_token.txt")
            return False

        self._client = yadisk.YaDisk(token=self.token)

        if not self._client.check_token():
            logger.error("YDisk token is invalid")
            self._client = None
            return False

        logger.info("Connected to Yandex Disk")
        self._ensure_remote_dir(self.remote_path)
        return True

    def upload_file(self, local_path: Path, subfolder: str = "") -> bool:
        """Upload a single file to Yandex Disk.

        Args:
            local_path: Path to the local file.
            subfolder: Optional subfolder under the remote base path.
        """
        if not self._client:
            logger.error("Not connected to YDisk")
            return False

        remote_dir = self.remote_path
        if subfolder:
            remote_dir = f"{self.remote_path}/{subfolder}"
            self._ensure_remote_dir(remote_dir)

        remote_file = f"{remote_dir}/{local_path.name}"

        try:
            self._client.upload(str(local_path), remote_file, overwrite=True)
            logger.info(f"Uploaded: {local_path.name} -> {remote_file}")
            return True
        except Exception as e:
            logger.error(f"Upload failed for {local_path.name}: {e}")
            return False

    def upload_directory(self, local_dir: Path, subfolder: str = "") -> dict:
        """Upload all files in a local directory to Yandex Disk.

        Returns a dict mapping filenames to upload success status.
        """
        results = {}
        if not local_dir.is_dir():
            logger.error(f"Not a directory: {local_dir}")
            return results

        for f in sorted(local_dir.iterdir()):
            if f.is_file():
                results[f.name] = self.upload_file(f, subfolder)

        return results

    def _ensure_remote_dir(self, path: str):
        """Create remote directory and parents if they don't exist."""
        parts = [p for p in path.split("/") if p]
        current = ""
        for part in parts:
            current += f"/{part}"
            try:
                if not self._client.exists(current):
                    self._client.mkdir(current)
                    logger.info(f"Created remote dir: {current}")
            except Exception as e:
                logger.warning(f"Could not check/create dir {current}: {e}")
