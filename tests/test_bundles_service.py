import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.services.bundles import (
    build_batch_zip,
    build_position_zip,
    bundle_name,
    mime_type_for,
    safe_file_part,
)


class BundlesServiceTests(unittest.TestCase):
    def test_safe_file_part_and_mime_type(self):
        self.assertEqual(safe_file_part('EDQM:ABC/123*"?'), "EDQM_ABC_123_")
        self.assertEqual(mime_type_for(Path("a.pdf")), "application/pdf")
        self.assertEqual(mime_type_for(Path("a.txt")), "text/plain")
        self.assertEqual(mime_type_for(Path("a.bin")), "application/octet-stream")

    def test_build_position_zip_preserves_coo_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coa = root / "coa.pdf"
            msds = root / "msds.pdf"
            coo = root / "France.txt"
            coa.write_bytes(b"coa")
            msds.write_bytes(b"msds")
            coo.write_bytes(b"France")

            bundle = bundle_name("edqm", "P123", "POSITION")
            payload = build_position_zip(bundle, {"COA": coa, "MSDS": msds, "COO": coo})

            with zipfile.ZipFile(io.BytesIO(payload), "r") as zf:
                names = sorted(zf.namelist())

            self.assertIn("France.txt", names)
            self.assertTrue(any(name.endswith("_COA.pdf") for name in names))
            self.assertTrue(any(name.endswith("_MSDS.pdf") for name in names))

    def test_build_batch_zip_writes_position_folders_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coa = root / "coa.pdf"
            coo = root / "France.txt"
            coa.write_bytes(b"coa")
            coo.write_bytes(b"France")

            successful = {"P123": {"COA": coa, "COO": coo}}
            positions = {"P123": "POSITION"}
            payload = build_batch_zip("edqm", successful, positions, manifest_text="ok")

            with zipfile.ZipFile(io.BytesIO(payload), "r") as zf:
                names = sorted(zf.namelist())
                self.assertIn("manifest.txt", names)
                self.assertTrue(any(name.endswith("/France.txt") for name in names))
                self.assertTrue(any("/" in name and name.endswith("_COA.pdf") for name in names))


if __name__ == "__main__":
    unittest.main()
