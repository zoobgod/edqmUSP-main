"""Vercel-compatible ASGI frontend for edqmUSP."""

from __future__ import annotations

import html
import re
import sys
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = FastAPI(title="edqmUSP")

APP_CSS = """
<style>
:root {
  --paper: #f4efe6;
  --paper-2: #fbf8f2;
  --ink: #1f1b17;
  --muted: #72685d;
  --muted-2: #8d8174;
  --card: rgba(255, 250, 242, 0.82);
  --line: rgba(106, 91, 73, 0.18);
  --line-strong: rgba(106, 91, 73, 0.28);
  --teal: #0d5c63;
  --teal-2: #12857a;
  --teal-soft: rgba(18, 133, 122, 0.12);
  --bronze: #a66a2b;
  --bronze-2: #c98b3c;
  --rose: #c45d53;
  --shadow: 0 22px 60px rgba(50, 35, 20, 0.10);
  --shadow-soft: 0 10px 28px rgba(50, 35, 20, 0.07);
  --radius-xl: 28px;
  --radius-lg: 20px;
  --radius-md: 16px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 15% 15%, rgba(201,139,60,0.22), transparent 22%),
    radial-gradient(circle at 88% 12%, rgba(13,92,99,0.18), transparent 24%),
    radial-gradient(circle at 80% 75%, rgba(18,133,122,0.10), transparent 18%),
    linear-gradient(180deg, var(--paper-2), var(--paper));
  color: var(--ink);
  font-family: "Manrope", "Segoe UI", sans-serif;
  min-height: 100vh;
  position: relative;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(93, 76, 58, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(93, 76, 58, 0.03) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: radial-gradient(circle at center, black 55%, transparent 92%);
  pointer-events: none;
  z-index: -1;
}
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 18px 80px;
}
.topbar {
  position: sticky;
  top: 18px;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  margin-bottom: 28px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(251, 248, 242, 0.72);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow-soft);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: #fff;
  font-family: "Fraunces", Georgia, serif;
  font-size: 1.35rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--teal), var(--teal-2));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.25);
}
.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.brand-title {
  font-family: "Fraunces", Georgia, serif;
  font-size: 1.1rem;
  font-weight: 600;
}
.brand-subtitle {
  color: var(--muted);
  font-size: 0.82rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.nav a {
  color: var(--ink);
  text-decoration: none;
  padding: 10px 16px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(255,250,242,0.78);
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease;
}
.nav a:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
  background: rgba(255,255,255,0.92);
}
.nav a.active {
  background: linear-gradient(135deg, var(--teal), var(--teal-2));
  color: #fff;
  border-color: transparent;
}
h1, h2, h3 {
  font-family: "Fraunces", Georgia, serif;
  letter-spacing: -0.03em;
}
h1 {
  font-size: clamp(2.8rem, 6vw, 5rem);
  margin: 0;
  line-height: 1.05;
}
h2 {
  font-size: clamp(1.5rem, 2.2vw, 2.2rem);
  margin: 0 0 10px;
}
h3 {
  font-size: 1.1rem;
  margin: 0 0 8px;
}
p {
  margin: 0;
  line-height: 1.7;
}
a {
  color: inherit;
}
.muted, .note {
  color: var(--muted);
}
.hero-shell,
.surface,
.table-panel,
.manifest-panel {
  position: relative;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(255,252,247,0.92), rgba(255,248,239,0.80));
  box-shadow: var(--shadow);
}
.hero-shell {
  overflow: hidden;
  padding: 34px;
  border-radius: var(--radius-xl);
}
.hero-shell::after {
  content: "";
  position: absolute;
  top: -90px;
  right: -60px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(201,139,60,0.20), rgba(201,139,60,0.02) 62%, transparent 70%);
  pointer-events: none;
}
.hero-grid {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 22px;
  align-items: start;
}
.hero-copy {
  display: grid;
  gap: 18px;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(13, 92, 99, 0.16);
  background: rgba(13, 92, 99, 0.08);
  color: var(--teal);
  font-size: 0.82rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.eyebrow::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--teal-2), var(--bronze-2));
}
.lede {
  max-width: 760px;
  color: var(--muted);
  font-size: 1.06rem;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.hero-aside,
.surface {
  border-radius: var(--radius-lg);
}
.hero-aside {
  padding: 22px;
  background:
    linear-gradient(180deg, rgba(13,92,99,0.08), rgba(255,255,255,0.65)),
    rgba(255,255,255,0.65);
  border: 1px solid rgba(13,92,99,0.12);
}
.hero-aside ul,
.feature-list,
.mini-list,
.step-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.hero-aside li,
.feature-list li,
.mini-list li,
.step-list li {
  position: relative;
  padding-left: 18px;
}
.hero-aside li::before,
.feature-list li::before,
.mini-list li::before,
.step-list li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0.72em;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--bronze-2), var(--teal-2));
  transform: translateY(-50%);
}
.hero-aside ul {
  display: grid;
  gap: 12px;
}
.hero-stats,
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.hero-stats {
  margin-top: 10px;
}
.stat {
  padding: 18px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.68);
  box-shadow: var(--shadow-soft);
}
.stat-value {
  display: block;
  margin-bottom: 8px;
  font-family: "Fraunces", Georgia, serif;
  font-size: 1.65rem;
}
.stat-label {
  color: var(--muted);
  font-size: 0.95rem;
}
.card {
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-soft);
  transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 16px 36px rgba(50, 35, 20, 0.10);
  border-color: var(--line-strong);
}
.button, button {
  display: inline-block;
  background: linear-gradient(135deg, var(--teal), var(--teal-2));
  color: #fff;
  border: 0;
  border-radius: 16px;
  padding: 13px 18px;
  font: inherit;
  font-weight: 800;
  letter-spacing: 0.01em;
  text-decoration: none;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(13, 92, 99, 0.18);
  transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
}
.button:hover, button:hover {
  transform: translateY(-1px);
  filter: saturate(1.06);
  box-shadow: 0 14px 28px rgba(13, 92, 99, 0.22);
}
.button.secondary, button.secondary {
  background: linear-gradient(135deg, var(--bronze), var(--bronze-2));
  box-shadow: 0 10px 24px rgba(166, 106, 43, 0.18);
}
.button.ghost {
  background: rgba(255,255,255,0.74);
  color: var(--ink);
  border: 1px solid var(--line);
  box-shadow: none;
}
.surface {
  margin-top: 22px;
  padding: 22px;
}
form {
  margin-top: 22px;
}
.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.72fr);
  gap: 18px;
  align-items: start;
}
.panel {
  padding: 22px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.70);
  box-shadow: var(--shadow-soft);
}
.field-group {
  display: grid;
  gap: 8px;
}
label {
  display: block;
  font-weight: 800;
  margin: 14px 0 8px;
  letter-spacing: 0.01em;
}
.field-hint {
  color: var(--muted-2);
  font-size: 0.92rem;
  margin-bottom: 2px;
}
textarea, select, input[type="text"] {
  width: 100%;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.88);
  font: inherit;
  color: var(--ink);
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}
textarea:focus, select:focus, input[type="text"]:focus {
  border-color: rgba(13, 92, 99, 0.35);
  box-shadow: 0 0 0 4px rgba(13, 92, 99, 0.10);
  background: #fff;
}
textarea {
  min-height: 198px;
  resize: vertical;
}
.checks {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 10px 0 18px;
}
.checks label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.78);
  font-weight: 700;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}
.checks label:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
  background: #fff;
}
.checks input {
  accent-color: var(--teal);
}
.table-wrap {
  overflow-x: auto;
}
.table-panel {
  margin-top: 24px;
  padding: 18px;
  border-radius: var(--radius-lg);
}
.table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 8px 6px 16px;
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: rgba(255,255,255,0.92);
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
}
th, td {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(106, 91, 73, 0.10);
  text-align: left;
  vertical-align: top;
}
th {
  background: rgba(239, 229, 214, 0.82);
  color: var(--muted);
  font-size: 0.82rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
tbody tr:nth-child(even) td {
  background: rgba(252, 248, 241, 0.56);
}
tbody tr:hover td {
  background: rgba(13, 92, 99, 0.05);
}
.status-ok {
  color: #165f58;
  font-weight: 700;
}
.status-fail {
  color: var(--rose);
  font-weight: 700;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 0.86rem;
  font-weight: 800;
  background: rgba(13, 92, 99, 0.08);
  color: var(--teal);
  border: 1px solid rgba(13, 92, 99, 0.12);
}
.status-pill.fail {
  background: rgba(196, 93, 83, 0.10);
  border-color: rgba(196, 93, 83, 0.16);
  color: var(--rose);
}
.note {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(166, 106, 43, 0.18);
  background: rgba(201, 139, 60, 0.10);
}
.manifest-panel {
  margin-top: 22px;
  padding: 18px;
  border-radius: var(--radius-lg);
}
.manifest-panel h3,
.table-panel h3,
.panel h3,
.hero-aside h3 {
  margin-bottom: 10px;
}
pre {
  white-space: pre-wrap;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255,255,255,0.88);
  padding: 16px;
  overflow-x: auto;
}
.section-stack {
  display: grid;
  gap: 22px;
}
.mini-list,
.step-list {
  display: grid;
  gap: 12px;
}
.microcopy {
  color: var(--muted-2);
  font-size: 0.88rem;
}
@media (max-width: 700px) {
  .page { padding: 14px 12px 48px; }
  .topbar {
    position: static;
    border-radius: 24px;
    align-items: flex-start;
    flex-direction: column;
  }
  .nav { justify-content: flex-start; }
  .hero-shell, .surface, .card, .panel, .hero-aside, .table-panel, .manifest-panel { padding: 18px; }
  h1 { font-size: clamp(2.2rem, 12vw, 3.4rem); }
}
@media (max-width: 900px) {
  .hero-grid, .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
"""


def _page(title: str, body: str, active: str = "") -> HTMLResponse:
    nav_items = [
        ("/", "Home", "home"),
        ("/download", "Download Documents", "download"),
        ("/lookup", "Find Catalogue Numbers", "lookup"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for href, label, key in nav_items
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    {APP_CSS}
  </head>
  <body>
    <main class="page">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">V</div>
          <div class="brand-copy">
            <div class="brand-title">edqmUSP</div>
            <div class="brand-subtitle">Instant regulatory document access</div>
          </div>
        </div>
        <nav class="nav">{nav_html}</nav>
      </header>
      {body}
    </main>
  </body>
</html>"""
    )


def _safe_text(value: str) -> str:
    return html.escape(value or "")


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]+', "_", (value or "").strip()).strip(".")
    return cleaned or "download"


def _parse_lines(raw: str) -> list[str]:
    values: list[str] = []
    for piece in re.split(r"[\r\n;]+", raw or ""):
        item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", piece).strip()
        if item:
            values.append(item)
    return values


def _bundle_name(source: str, code: str, position_name: str) -> str:
    return f"{source.upper()}_{code}_{position_name}".strip()


def _zip_member_name(bundle_name: str, doc_type: str, file_path: Path) -> str:
    if doc_type == "COO":
        return file_path.name
    suffix = file_path.suffix.lower() or ".pdf"
    return f"{_safe_filename(bundle_name)}_{doc_type}{suffix}"


def _build_position_zip(bundle_name: str, files_by_doc: dict[str, Path]) -> bytes:
    buffer = BytesIO()
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
    manifest_text: str,
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for code, files_by_doc in successful_files.items():
            position_name = position_names.get(code, code)
            bundle_name = _bundle_name(source, code, position_name)
            archive.writestr(
                f"{_safe_filename(bundle_name)}.zip",
                _build_position_zip(bundle_name, files_by_doc),
            )
        archive.writestr("manifest.txt", manifest_text)
    buffer.seek(0)
    return buffer.getvalue()


def _resolve_position_name(downloader, code: str) -> str:
    getter = getattr(downloader, "get_position_name", None)
    if callable(getter):
        try:
            name = (getter(code) or "").strip()
            if name:
                return name
        except Exception:
            return code
    return code


def _download_batch(source: str, codes: list[str], doc_types: list[str]) -> tuple[bytes, str, int]:
    if source == "edqm":
        from src.downloaders.edqm import EDQMDownloader as DownloaderCls
    else:
        from src.downloaders.usp import USPDownloader as DownloaderCls

    successful_files: dict[str, dict[str, Path]] = {}
    position_names: dict[str, str] = {}
    manifest_lines = [
        f"Batch generated: {datetime.utcnow().isoformat()}Z",
        f"Source: {source.upper()}",
        f"Requested document types: {', '.join(doc_types)}",
        "",
    ]

    with TemporaryDirectory() as tmpdir:
        downloader = DownloaderCls(download_dir=Path(tmpdir))
        downloader.start()
        try:
            for code in codes:
                manifest_lines.append(f"[{code}]")
                if downloader.search_product(code):
                    position_names[code] = _resolve_position_name(downloader, code)
                    for doc in doc_types:
                        result = downloader.download_document(code, doc)
                        if result.success:
                            file_path = Path(result.file_path)
                            successful_files.setdefault(code, {})[doc] = file_path
                            manifest_lines.append(f"  {doc}: OK -> {file_path.name}")
                        else:
                            manifest_lines.append(f"  {doc}: FAIL -> {result.error}")
                else:
                    for doc in doc_types:
                        manifest_lines.append(f"  {doc}: FAIL -> Product not found")
                manifest_lines.append("")
        finally:
            downloader.stop()

        manifest_text = "\n".join(manifest_lines)
        if not successful_files:
            return b"", manifest_text, 0
        batch_zip = _build_batch_zip(source, successful_files, position_names, manifest_text)
        return batch_zip, manifest_text, len(successful_files)


def _lookup_catalogue_numbers(source: str, names: list[str], limit: int = 8) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source = source.lower()

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        if source in {"edqm", "both"}:
            from src.downloaders.edqm import EDQMDownloader

            with EDQMDownloader(download_dir=tmp_path) as downloader:
                for query in names:
                    matches = downloader.search_products_by_name(query, limit=limit)
                    if matches:
                        for match in matches:
                            rows.append(
                                {
                                    "query": query,
                                    "source": "EDQM",
                                    "code": match.product_code,
                                    "name": match.name,
                                }
                            )
                    else:
                        rows.append({"query": query, "source": "EDQM", "code": "", "name": "No match found"})

        if source in {"usp", "both"}:
            from src.downloaders.usp import USPDownloader

            with USPDownloader(download_dir=tmp_path) as downloader:
                for query in names:
                    matches = downloader.search_products_by_name(query, limit=limit)
                    if matches:
                        for match in matches:
                            rows.append(
                                {
                                    "query": query,
                                    "source": "USP",
                                    "code": match.product_code,
                                    "name": match.name,
                                }
                            )
                    else:
                        rows.append({"query": query, "source": "USP", "code": "", "name": "No match found"})

    return rows


def _download_form(
    source: str = "edqm",
    codes: str = "",
    message: str = "",
    selected_docs: list[str] | None = None,
) -> str:
    source = source.lower()
    active_docs = {doc.upper() for doc in (selected_docs or ["COA", "MSDS", "COO"])}
    checked = lambda doc: "checked" if doc.upper() in active_docs else ""
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">Batch Download Workspace</span>
      <h1>Generate one clean ZIP instead of searching every catalogue page by hand.</h1>
      <p class="lede">Drop in EDQM or USP catalogue numbers, select the documents you need, and let the app assemble a download-ready batch with position-level bundles and a manifest.</p>
      {note}
      <div class="hero-stats">
        <div class="grid">
          <div class="stat">
            <span class="stat-value">3 docs</span>
            <span class="stat-label">COA, MSDS, and COO bundled around each position</span>
          </div>
          <div class="stat">
            <span class="stat-value">1 ZIP</span>
            <span class="stat-label">Batch archive generated in one step for the whole request</span>
          </div>
          <div class="stat">
            <span class="stat-value">0 login</span>
            <span class="stat-label">Public catalogue access with the same downloader logic as the local app</span>
          </div>
        </div>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>How this batch is structured</h3>
      <ul>
        <li>Each position gets its own nested ZIP named after source, code, and position name.</li>
        <li>The outer archive includes a manifest so failed documents are still visible.</li>
        <li>EDQM COO keeps the source file and is renamed by country. USP COO remains a country-named text file.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=download" class="panel">
      <h2>Download Documents</h2>
      <p class="muted">Built for quick bulk retrieval when you already know the catalogue numbers.</p>

      <div class="field-group">
        <label for="source">Source</label>
        <div class="field-hint">Choose the catalogue family to search.</div>
        <select id="source" name="source">
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="codes">Catalogue numbers</label>
        <div class="field-hint">Paste one code per line. Lists copied from spreadsheets are fine.</div>
        <textarea id="codes" name="codes" placeholder="Y0001532&#10;G0400006&#10;1134357">{_safe_text(codes)}</textarea>
      </div>

      <div class="field-group">
        <label>Documents to include</label>
        <div class="field-hint">Select only the document types you want packed into the batch ZIP.</div>
        <div class="checks">
          <label><input type="checkbox" name="doc_types" value="COA" {checked("COA")}> COA</label>
          <label><input type="checkbox" name="doc_types" value="MSDS" {checked("MSDS")}> MSDS</label>
          <label><input type="checkbox" name="doc_types" value="COO" {checked("COO")}> COO</label>
        </div>
      </div>

      <button type="submit">Generate Batch ZIP</button>
      <div class="microcopy" style="margin-top: 12px;">The ZIP downloads directly from this page when the request completes.</div>
    </form>

    <aside class="panel section-stack">
      <div>
        <h3>Best results</h3>
        <ul class="mini-list">
          <li>Use exact catalogue numbers if you already have them from a spreadsheet or ERP.</li>
          <li>Mixing EDQM and USP codes in one request is not supported, so run one source at a time.</li>
          <li>If some documents are unavailable, the manifest will show exactly which step failed.</li>
        </ul>
      </div>
      <div>
        <h3>Typical workflow</h3>
        <ul class="step-list">
          <li>Pick the source.</li>
          <li>Paste your codes in bulk.</li>
          <li>Download the generated archive and distribute the nested position ZIPs.</li>
        </ul>
      </div>
    </aside>
  </div>
</section>
"""


def _lookup_form(source: str = "both", names: str = "", table_html: str = "", message: str = "") -> str:
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">Catalogue Finder</span>
      <h1>Start from product names and work backward to the right catalogue numbers.</h1>
      <p class="lede">Use this page when you have raw product names from procurement, QC, or a client list and need to resolve them into EDQM or USP catalogue numbers in bulk.</p>
      {note}
      <div class="hero-actions">
        <a class="button secondary" href="/download">Already have the codes? Go straight to downloads</a>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>Designed for bulk lists</h3>
      <ul>
        <li>Paste one product name per line.</li>
        <li>Search EDQM, USP, or both in one pass.</li>
        <li>Review the results table and use the matched codes in the downloader.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=lookup" class="panel">
      <h2>Find Catalogue Numbers</h2>
      <p class="muted">A faster alternative to opening the catalogue websites and searching each item by hand.</p>

      <div class="field-group">
        <label for="source">Where should we search?</label>
        <div class="field-hint">Use both if you are unsure whether the product belongs to EDQM or USP.</div>
        <select id="source" name="source">
          <option value="both" {"selected" if source == "both" else ""}>Both</option>
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="names">Product names, one per line</label>
        <div class="field-hint">Free-form names are okay. The search returns the closest public catalogue matches it can find.</div>
        <textarea id="names" name="names" placeholder="PICOTAMIDE MONOHYDRATE CRS&#10;Cisplatin&#10;Glycerol Monostearate 40-55 CRS">{_safe_text(names)}</textarea>
      </div>

      <button type="submit" class="secondary">Find Matching Catalogue Numbers</button>
    </form>

    <aside class="panel section-stack">
      <div>
        <h3>Good input examples</h3>
        <ul class="mini-list">
          <li>Full pharmacopoeia name if you have it.</li>
          <li>Short material name like <code>Cisplatin</code>.</li>
          <li>Multiple positions pasted from a customer request or spreadsheet.</li>
        </ul>
      </div>
      <div>
        <h3>After the lookup</h3>
        <ul class="step-list">
          <li>Copy the matching codes from the results table.</li>
          <li>Open the downloader page.</li>
          <li>Generate the document ZIP for the selected positions.</li>
        </ul>
      </div>
    </aside>
  </div>
  {table_html}
</section>
"""


def _lookup_results_table(rows: list[dict[str, str]]) -> str:
    success_count = sum(1 for row in rows if row["code"])
    failed_count = len(rows) - success_count
    body = []
    for row in rows:
        status = row["code"] if row["code"] else "No match"
        klass = "status-ok" if row["code"] else "status-fail"
        body.append(
            "<tr>"
            f"<td>{_safe_text(row['query'])}</td>"
            f"<td>{_safe_text(row['source'])}</td>"
            f'<td class="{klass}">{_safe_text(status)}</td>'
            f"<td>{_safe_text(row['name'])}</td>"
            "</tr>"
        )
    return (
        '<section class="table-panel">'
        '<div class="table-header">'
        '<div><h3>Lookup Results</h3><p class="muted">Review the closest public catalogue matches returned by the live search.</p></div>'
        f'<div style="display:flex; gap:10px; flex-wrap:wrap;"><span class="status-pill">{success_count} matches</span>'
        f'<span class="status-pill {"fail" if failed_count else ""}">{failed_count} no-match rows</span></div>'
        "</div>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Query</th><th>Source</th><th>Catalogue Number</th><th>Product Name</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></section>"
    )


@app.get("/", response_class=HTMLResponse)
def landing_page() -> HTMLResponse:
    body = """
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">Regulatory Download Toolkit</span>
      <h1>Replace catalogue hunting with a cleaner, faster workflow.</h1>
      <p class="lede">edqmUSP is built to save time when you need certificates and safety documents now, not after opening dozens of catalogue pages. Resolve product names into codes, then generate download-ready ZIPs from the same domain.</p>
      <div class="hero-actions">
        <a class="button" href="/download">Open Downloader</a>
        <a class="button ghost" href="/lookup">Find Catalogue Numbers</a>
      </div>
      <div class="hero-stats">
        <div class="grid">
          <div class="stat">
            <span class="stat-value">EDQM + USP</span>
            <span class="stat-label">Two public catalogue sources in one workflow</span>
          </div>
          <div class="stat">
            <span class="stat-value">Bulk-first</span>
            <span class="stat-label">Paste many names or codes at once instead of working one position at a time</span>
          </div>
          <div class="stat">
            <span class="stat-value">Nested ZIPs</span>
            <span class="stat-label">One batch archive containing organized position bundles</span>
          </div>
        </div>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>What this deployment does well</h3>
      <ul>
        <li>Direct document retrieval for COA, MSDS, and COO by catalogue number.</li>
        <li>Bulk catalogue lookup by product name when the code is missing.</li>
        <li>Organized outputs that are easier to pass downstream to QA, purchasing, or clients.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="grid">
    <section class="card">
      <h2>Download Documents</h2>
      <p class="muted">Use this when you already know the catalogue numbers and want the files packaged immediately.</p>
      <ul class="feature-list" style="display:grid; gap:10px; margin:16px 0 18px;">
        <li>Batch ZIP output with nested position bundles.</li>
        <li>COA, MSDS, and COO selection in one request.</li>
        <li>Manifest included so missing files are visible without guessing.</li>
      </ul>
      <a class="button" href="/download">Open Downloader</a>
    </section>
    <section class="card">
      <h2>Find Catalogue Numbers</h2>
      <p class="muted">Use this when you only have product names and need to resolve them into working EDQM or USP codes.</p>
      <ul class="feature-list" style="display:grid; gap:10px; margin:16px 0 18px;">
        <li>Bulk search by product name, one line per item.</li>
        <li>Cross-search EDQM, USP, or both.</li>
        <li>Results table built for quick copy-and-download workflow.</li>
      </ul>
      <a class="button secondary" href="/lookup">Open Catalogue Finder</a>
    </section>
  </div>
</section>
"""
    return _page("edqmUSP", body, active="home")


async def _handle_vercel_entry(request: Request):
    page = (request.query_params.get("page") or "home").lower()
    path = request.url.path.rstrip("/")

    if path.endswith("/download"):
        page = "download"
    elif path.endswith("/lookup"):
        page = "lookup"
    elif path.endswith("/health"):
        page = "health"

    if page == "health":
        return PlainTextResponse("ok")

    if request.method == "GET":
        if page == "download":
            return download_page()
        if page == "lookup":
            return lookup_page()
        return landing_page()

    raw_body = await request.body()
    parsed_form = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)

    def form_first(name: str, default: str = "") -> str:
        values = parsed_form.get(name)
        return values[0] if values else default

    def form_list(name: str) -> list[str]:
        return parsed_form.get(name, [])

    if page == "download":
        source = form_first("source", "edqm")
        codes = form_first("codes", "")
        doc_types = [str(value) for value in form_list("doc_types")]
        return download_documents(source=source, codes=codes, doc_types=doc_types)

    if page == "lookup":
        source = form_first("source", "both")
        names = form_first("names", "")
        return lookup_catalogue_numbers(source=source, names=names)

    return landing_page()


@app.get("/download", response_class=HTMLResponse)
def download_page() -> HTMLResponse:
    return _page("Download Documents", _download_form(), active="download")


@app.post("/download")
def download_documents(
    source: str = Form(...),
    codes: str = Form(""),
    doc_types: list[str] = Form(default_factory=list),
):
    source = source.lower().strip()
    clean_codes = _parse_lines(codes)
    clean_doc_types = [doc.upper() for doc in doc_types if doc.upper() in {"COA", "MSDS", "COO"}]

    if source not in {"edqm", "usp"}:
        return _page(
            "Download Documents",
            _download_form(source="edqm", codes=codes, message="Invalid source.", selected_docs=clean_doc_types),
            active="download",
        )
    if not clean_codes:
        return _page(
            "Download Documents",
            _download_form(source=source, codes=codes, message="Enter at least one catalogue number.", selected_docs=clean_doc_types),
            active="download",
        )
    if not clean_doc_types:
        return _page(
            "Download Documents",
            _download_form(source=source, codes=codes, message="Select at least one document type.", selected_docs=[]),
            active="download",
        )

    try:
        batch_zip, manifest_text, position_count = _download_batch(source, clean_codes, clean_doc_types)
    except Exception as exc:
        body = _download_form(
            source=source,
            codes=codes,
            message=f"Download failed: {exc}",
            selected_docs=clean_doc_types,
        )
        return _page("Download Documents", body, active="download")

    if not batch_zip:
        body = (
            _download_form(
                source=source,
                codes=codes,
                message="No files were downloaded. See manifest below.",
                selected_docs=clean_doc_types,
            )
            + f'<section class="manifest-panel"><h3>Batch Manifest</h3><pre>{_safe_text(manifest_text)}</pre></section>'
        )
        return _page("Download Documents", body, active="download")

    filename = f"{source.upper()}_BATCH_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{position_count}pos.zip"
    return StreamingResponse(
        BytesIO(batch_zip),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/lookup", response_class=HTMLResponse)
def lookup_page() -> HTMLResponse:
    return _page("Find Catalogue Numbers", _lookup_form(), active="lookup")


@app.post("/lookup", response_class=HTMLResponse)
def lookup_catalogue_numbers(
    source: str = Form("both"),
    names: str = Form(""),
):
    clean_names = _parse_lines(names)
    if not clean_names:
        return _page(
            "Find Catalogue Numbers",
            _lookup_form(source=source, names=names, message="Enter at least one product name."),
            active="lookup",
        )

    try:
        rows = _lookup_catalogue_numbers(source, clean_names)
    except Exception as exc:
        return _page(
            "Find Catalogue Numbers",
            _lookup_form(source=source, names=names, message=f"Lookup failed: {exc}"),
            active="lookup",
        )

    table_html = _lookup_results_table(rows)
    return _page(
        "Find Catalogue Numbers",
        _lookup_form(source=source, names=names, table_html=table_html),
        active="lookup",
    )


@app.get("/health", response_class=PlainTextResponse)
def healthcheck() -> str:
    return "ok"


@app.api_route("/api/index.py", methods=["GET", "POST"])
async def vercel_index_entry(request: Request):
    return await _handle_vercel_entry(request)
