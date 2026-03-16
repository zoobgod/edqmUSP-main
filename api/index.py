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
  --bg: #0b0f14;
  --bg-2: #0f141b;
  --panel: rgba(16, 22, 31, 0.96);
  --panel-2: rgba(19, 26, 36, 0.98);
  --panel-3: rgba(13, 18, 26, 0.98);
  --text: #e6edf3;
  --muted: #9fb0c3;
  --muted-2: #7f93aa;
  --line: rgba(139, 162, 186, 0.18);
  --line-strong: rgba(139, 162, 186, 0.34);
  --blue: #2f81f7;
  --blue-2: #1f6feb;
  --green: #3fb950;
  --red: #f85149;
  --shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
  --shadow-soft: 0 12px 30px rgba(0, 0, 0, 0.24);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 15% 10%, rgba(47,129,247,0.28), transparent 22%),
    radial-gradient(circle at 75% 0%, rgba(88,166,255,0.18), transparent 24%),
    radial-gradient(circle at 40% 35%, rgba(99,102,241,0.20), transparent 26%),
    linear-gradient(180deg, #0a0f15, #090d12 55%, #0b1016);
  color: var(--text);
  font-family: "Segoe UI", "Inter", system-ui, sans-serif;
  min-height: 100vh;
  position: relative;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.022) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: radial-gradient(circle at center, black 52%, transparent 92%);
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
  background: rgba(11, 15, 20, 0.88);
  backdrop-filter: blur(18px);
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
  color: #fff;
  font-size: 1.25rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--blue), var(--blue-2));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.10);
}
.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.brand-title {
  font-size: 1rem;
  font-weight: 600;
}
.brand-subtitle {
  color: var(--muted);
  font-size: 0.82rem;
  letter-spacing: 0.02em;
}
.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
}
.nav a {
  color: var(--text);
  text-decoration: none;
  padding: 10px 16px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.02);
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease;
}
.nav a:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
  background: rgba(255,255,255,0.06);
}
.nav a.active {
  background: linear-gradient(135deg, var(--blue), var(--blue-2));
  color: #fff;
  border-color: transparent;
}
.nav .lang-link {
  min-width: 58px;
  text-align: center;
}
h1 {
  font-size: clamp(2rem, 5vw, 3rem);
  margin: 0;
  line-height: 1.15;
  font-weight: 650;
}
h2 {
  font-size: clamp(1.2rem, 2vw, 1.6rem);
  margin: 0 0 10px;
  font-weight: 600;
}
h3 {
  font-size: 1rem;
  margin: 0 0 8px;
  font-weight: 600;
}
p {
  margin: 0;
  line-height: 1.55;
}
a { color: inherit; }
.muted, .note { color: var(--muted); }
.hero-shell,
.surface,
.table-panel,
.manifest-panel {
  position: relative;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(15,20,27,0.92), rgba(13,18,26,0.98));
  box-shadow: var(--shadow);
}
.hero-shell {
  overflow: hidden;
  padding: 28px;
}
.hero-shell::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 10% 10%, rgba(88,166,255,0.22), transparent 22%),
    radial-gradient(circle at 85% 8%, rgba(99,102,241,0.26), transparent 24%),
    radial-gradient(circle at 32% 100%, rgba(63,185,80,0.14), transparent 26%);
  pointer-events: none;
}
.hero-grid {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
  gap: 22px;
  align-items: start;
}
.hero-copy {
  display: grid;
  gap: 14px;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 7px 10px;
  border: 1px solid rgba(47,129,247,0.20);
  background: rgba(47,129,247,0.10);
  color: #91c3ff;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.eyebrow::before {
  content: "";
  width: 8px;
  height: 8px;
  background: linear-gradient(135deg, #7ee787, var(--blue));
}
.lede {
  max-width: 760px;
  color: var(--muted);
  font-size: 0.98rem;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.hero-aside {
  padding: 20px;
  background:
    linear-gradient(180deg, rgba(47,129,247,0.08), rgba(15,20,27,0.94)),
    rgba(15,20,27,0.94);
  border: 1px solid var(--line);
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
  background: linear-gradient(135deg, #7ee787, var(--blue));
  transform: translateY(-50%);
}
.hero-aside ul,
.mini-list,
.step-list,
.feature-list {
  display: grid;
  gap: 12px;
}
.hero-stats,
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
.hero-stats {
  margin-top: 10px;
}
.stat {
  padding: 18px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.03);
  box-shadow: var(--shadow-soft);
}
.stat-value {
  display: block;
  margin-bottom: 8px;
  font-size: 1.25rem;
  font-weight: 650;
}
.stat-label {
  color: var(--muted);
  font-size: 0.95rem;
}
.card {
  padding: 22px;
  border: 1px solid var(--line);
  background: rgba(15,20,27,0.94);
  box-shadow: var(--shadow-soft);
  transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.30);
  border-color: var(--line-strong);
}
.button, button {
  display: inline-block;
  background: linear-gradient(135deg, var(--blue), var(--blue-2));
  color: #fff;
  border: 0;
  padding: 13px 18px;
  font: inherit;
  font-weight: 700;
  letter-spacing: 0.01em;
  text-decoration: none;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(31, 111, 235, 0.20);
  transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
}
.button:hover, button:hover {
  transform: translateY(-1px);
  filter: saturate(1.06);
  box-shadow: 0 14px 28px rgba(31, 111, 235, 0.24);
}
.button.secondary, button.secondary {
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line);
  box-shadow: none;
}
.button.ghost {
  background: rgba(255,255,255,0.02);
  color: var(--text);
  border: 1px solid var(--line);
  box-shadow: none;
}
.surface {
  margin-top: 22px;
  padding: 22px;
}
form { margin-top: 22px; }
.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.72fr);
  gap: 18px;
  align-items: start;
}
.panel {
  padding: 22px;
  border: 1px solid var(--line);
  background: rgba(15,20,27,0.92);
  box-shadow: var(--shadow-soft);
}
.field-group {
  display: grid;
  gap: 8px;
}
label {
  display: block;
  font-weight: 700;
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
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.03);
  font: inherit;
  color: var(--text);
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}
textarea:focus, select:focus, input[type="text"]:focus {
  border-color: rgba(47,129,247,0.55);
  box-shadow: 0 0 0 3px rgba(47,129,247,0.14);
  background: rgba(255,255,255,0.05);
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
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.03);
  font-weight: 700;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}
.checks label:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
  background: rgba(255,255,255,0.06);
}
.checks input {
  accent-color: var(--blue);
}
.table-wrap { overflow-x: auto; }
.table-panel {
  margin-top: 24px;
  padding: 18px;
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
  background: rgba(15,20,27,0.98);
  border: 1px solid var(--line);
  overflow: hidden;
}
th, td {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(139, 162, 186, 0.10);
  text-align: left;
  vertical-align: top;
}
th {
  background: rgba(255,255,255,0.03);
  color: var(--muted);
  font-size: 0.82rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
tbody tr:nth-child(even) td {
  background: rgba(255,255,255,0.015);
}
tbody tr:hover td {
  background: rgba(47,129,247,0.06);
}
.status-ok {
  color: var(--green);
  font-weight: 700;
}
.status-fail {
  color: var(--red);
  font-weight: 700;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 0.86rem;
  font-weight: 700;
  background: rgba(47,129,247,0.10);
  color: #91c3ff;
  border: 1px solid rgba(47,129,247,0.18);
}
.status-pill.fail {
  background: rgba(248,81,73,0.10);
  border-color: rgba(248,81,73,0.18);
  color: #ffb3ad;
}
.note {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(47,129,247,0.18);
  background: rgba(47,129,247,0.08);
}
.manifest-panel {
  margin-top: 22px;
  padding: 18px;
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
  background: rgba(255,255,255,0.03);
  padding: 16px;
  overflow-x: auto;
}
.section-stack {
  display: grid;
  gap: 22px;
}
.microcopy {
  color: var(--muted-2);
  font-size: 0.88rem;
}
@media (max-width: 700px) {
  .page { padding: 14px 12px 48px; }
  .topbar {
    position: static;
    align-items: flex-start;
    flex-direction: column;
  }
  .nav { justify-content: flex-start; }
  .hero-shell, .surface, .card, .panel, .hero-aside, .table-panel, .manifest-panel { padding: 18px; }
  h1 { font-size: clamp(1.8rem, 10vw, 2.5rem); }
}
@media (max-width: 900px) {
  .hero-grid, .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
"""


UI_TEXT = {
    "ru": {
        "brand_subtitle": "Документы EDQM и USP",
        "nav_home": "Главная",
        "nav_download": "Загрузка",
        "nav_lookup": "Поиск кодов",
        "lang_switch": "EN",
    },
    "en": {
        "brand_subtitle": "EDQM and USP Documents",
        "nav_home": "Home",
        "nav_download": "Download",
        "nav_lookup": "Lookup",
        "lang_switch": "RU",
    },
}


def _normalize_lang(value: str | None) -> str:
    return "en" if (value or "").lower() == "en" else "ru"


def _t(lang: str, key: str) -> str:
    return UI_TEXT[_normalize_lang(lang)][key]


def _with_lang(path: str, lang: str) -> str:
    lang = _normalize_lang(lang)
    joiner = "&" if "?" in path else "?"
    return f"{path}{joiner}lang={lang}"


def _page(title: str, body: str, active: str = "", lang: str = "ru") -> HTMLResponse:
    lang = _normalize_lang(lang)
    current_path = {
        "home": "/",
        "download": "/download",
        "lookup": "/lookup",
    }.get(active or "home", "/")
    nav_items = [
        ("/", _t(lang, "nav_home"), "home"),
        ("/download", _t(lang, "nav_download"), "download"),
        ("/lookup", _t(lang, "nav_lookup"), "lookup"),
    ]
    nav_html = "".join(
        f'<a href="{_with_lang(href, lang)}" class="{"active" if key == active else ""}">{label}</a>'
        for href, label, key in nav_items
    )
    other_lang = "en" if lang == "ru" else "ru"
    return HTMLResponse(
        f"""<!doctype html>
<html lang="{lang}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    {APP_CSS}
  </head>
  <body>
    <main class="page">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">V</div>
          <div class="brand-copy">
            <div class="brand-title">edqmUSP</div>
            <div class="brand-subtitle">{_t(lang, "brand_subtitle")}</div>
          </div>
        </div>
        <nav class="nav">{nav_html}<a class="lang-link" href="{_with_lang(current_path, other_lang)}">{_t(lang, 'lang_switch')}</a></nav>
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
    lang: str = "ru",
) -> str:
    lang = _normalize_lang(lang)
    source = source.lower()
    active_docs = {doc.upper() for doc in (selected_docs or ["COA", "MSDS", "COO"])}
    checked = lambda doc: "checked" if doc.upper() in active_docs else ""
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    copy = {
        "ru": {
            "tag": "Загрузка",
            "title": "Пакетная загрузка",
            "subtitle": "Вставьте каталожные номера и получите ZIP.",
            "side_title": "Формат",
            "side_items": [
                "Один источник за запрос.",
                "ZIP создается сразу после выполнения.",
                "При ошибках ниже показывается манифест.",
            ],
            "form_title": "Параметры",
            "form_subtitle": "Без лишнего текста. Только ввод и результат.",
            "source": "Источник",
            "source_hint": "EDQM или USP.",
            "codes": "Каталожные номера",
            "codes_hint": "По одному номеру в строке.",
            "docs": "Документы",
            "docs_hint": "Выберите типы файлов.",
            "button": "Скачать ZIP",
            "micro": "Файл начнет скачиваться после завершения запроса.",
            "help_title": "Подсказки",
            "help_items": [
                "Не смешивайте EDQM и USP в одном списке.",
                "Если часть файлов не найдена, манифест покажет причину.",
                "Коды можно вставлять прямо из таблицы.",
            ],
        },
        "en": {
            "tag": "Download",
            "title": "Batch Download",
            "subtitle": "Paste catalogue numbers and get a ZIP.",
            "side_title": "Format",
            "side_items": [
                "One source per request.",
                "The ZIP is created immediately after processing.",
                "If something fails, the manifest is shown below.",
            ],
            "form_title": "Parameters",
            "form_subtitle": "Minimal UI. Input and result.",
            "source": "Source",
            "source_hint": "EDQM or USP.",
            "codes": "Catalogue numbers",
            "codes_hint": "One per line.",
            "docs": "Documents",
            "docs_hint": "Select file types.",
            "button": "Download ZIP",
            "micro": "The file download starts when the request finishes.",
            "help_title": "Notes",
            "help_items": [
                "Do not mix EDQM and USP in one list.",
                "If some files are missing, the manifest shows the reason.",
                "You can paste codes directly from a spreadsheet.",
            ],
        },
    }[lang]
    return f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">{copy["tag"]}</span>
      <h1>{copy["title"]}</h1>
      <p class="lede">{copy["subtitle"]}</p>
      {note}
    </div>
    <aside class="hero-aside">
      <h3>{copy["side_title"]}</h3>
      <ul>
        <li>{copy["side_items"][0]}</li>
        <li>{copy["side_items"][1]}</li>
        <li>{copy["side_items"][2]}</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=download" class="panel">
      <input type="hidden" name="lang" value="{lang}">
      <h2>{copy["form_title"]}</h2>
      <p class="muted">{copy["form_subtitle"]}</p>

      <div class="field-group">
        <label for="source">{copy["source"]}</label>
        <div class="field-hint">{copy["source_hint"]}</div>
        <select id="source" name="source">
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="codes">{copy["codes"]}</label>
        <div class="field-hint">{copy["codes_hint"]}</div>
        <textarea id="codes" name="codes" placeholder="Y0001532&#10;G0400006&#10;1134357">{_safe_text(codes)}</textarea>
      </div>

      <div class="field-group">
        <label>{copy["docs"]}</label>
        <div class="field-hint">{copy["docs_hint"]}</div>
        <div class="checks">
          <label><input type="checkbox" name="doc_types" value="COA" {checked("COA")}> COA</label>
          <label><input type="checkbox" name="doc_types" value="MSDS" {checked("MSDS")}> MSDS</label>
          <label><input type="checkbox" name="doc_types" value="COO" {checked("COO")}> COO</label>
        </div>
      </div>

      <button type="submit">{copy["button"]}</button>
      <div class="microcopy" style="margin-top: 12px;">{copy["micro"]}</div>
    </form>

    <aside class="panel">
      <div>
        <h3>{copy["help_title"]}</h3>
        <ul class="mini-list">
          <li>{copy["help_items"][0]}</li>
          <li>{copy["help_items"][1]}</li>
          <li>{copy["help_items"][2]}</li>
        </ul>
      </div>
    </aside>
  </div>
</section>
"""


def _lookup_form(source: str = "both", names: str = "", table_html: str = "", message: str = "", lang: str = "ru") -> str:
    lang = _normalize_lang(lang)
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    copy = {
        "ru": {
            "tag": "Поиск кодов",
            "title": "Поиск по названию",
            "subtitle": "Вставьте названия продуктов и получите каталожные номера.",
            "link": "Перейти к загрузке",
            "side_title": "Режим",
            "side_items": [
                "По одному названию в строке.",
                "Можно искать в EDQM, USP или сразу в обоих.",
                "Результат выводится в таблицу ниже.",
            ],
            "form_title": "Параметры",
            "form_subtitle": "Поиск каталожных номеров по названиям.",
            "source": "Где искать",
            "source_hint": "Если не уверены, выберите оба источника.",
            "names": "Названия продуктов",
            "names_hint": "По одному названию в строке.",
            "button": "Найти",
            "help_title": "Примеры",
            "help_items": [
                "PICOTAMIDE MONOHYDRATE CRS",
                "Cisplatin",
                "Glycerol Monostearate 40-55 CRS",
            ],
        },
        "en": {
            "tag": "Lookup",
            "title": "Lookup by Name",
            "subtitle": "Paste product names and get catalogue numbers.",
            "link": "Go to download",
            "side_title": "Mode",
            "side_items": [
                "One name per line.",
                "Search EDQM, USP, or both.",
                "Results appear in the table below.",
            ],
            "form_title": "Parameters",
            "form_subtitle": "Catalogue number lookup by product name.",
            "source": "Search in",
            "source_hint": "Choose both if you are unsure.",
            "names": "Product names",
            "names_hint": "One product name per line.",
            "button": "Find",
            "help_title": "Examples",
            "help_items": [
                "PICOTAMIDE MONOHYDRATE CRS",
                "Cisplatin",
                "Glycerol Monostearate 40-55 CRS",
            ],
        },
    }[lang]
    return f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">{copy["tag"]}</span>
      <h1>{copy["title"]}</h1>
      <p class="lede">{copy["subtitle"]}</p>
      {note}
      <div class="hero-actions">
        <a class="button secondary" href="{_with_lang('/download', lang)}">{copy["link"]}</a>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>{copy["side_title"]}</h3>
      <ul>
        <li>{copy["side_items"][0]}</li>
        <li>{copy["side_items"][1]}</li>
        <li>{copy["side_items"][2]}</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=lookup" class="panel">
      <input type="hidden" name="lang" value="{lang}">
      <h2>{copy["form_title"]}</h2>
      <p class="muted">{copy["form_subtitle"]}</p>

      <div class="field-group">
        <label for="source">{copy["source"]}</label>
        <div class="field-hint">{copy["source_hint"]}</div>
        <select id="source" name="source">
          <option value="both" {"selected" if source == "both" else ""}>{"Оба" if lang == "ru" else "Both"}</option>
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="names">{copy["names"]}</label>
        <div class="field-hint">{copy["names_hint"]}</div>
        <textarea id="names" name="names" placeholder="PICOTAMIDE MONOHYDRATE CRS&#10;Cisplatin&#10;Glycerol Monostearate 40-55 CRS">{_safe_text(names)}</textarea>
      </div>

      <button type="submit" class="secondary">{copy["button"]}</button>
    </form>

    <aside class="panel">
      <div>
        <h3>{copy["help_title"]}</h3>
        <ul class="mini-list">
          <li>{copy["help_items"][0]}</li>
          <li>{copy["help_items"][1]}</li>
          <li>{copy["help_items"][2]}</li>
        </ul>
      </div>
    </aside>
  </div>
  {table_html}
</section>
"""


def _lookup_results_table(rows: list[dict[str, str]], lang: str = "ru") -> str:
    lang = _normalize_lang(lang)
    success_count = sum(1 for row in rows if row["code"])
    failed_count = len(rows) - success_count
    body = []
    for row in rows:
        status = row["code"] if row["code"] else ("Нет совпадения" if lang == "ru" else "No match")
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
        f'<div><h3>{"Результаты" if lang == "ru" else "Results"}</h3><p class="muted">{"Таблица совпадений." if lang == "ru" else "Match table."}</p></div>'
        f'<div style="display:flex; gap:10px; flex-wrap:wrap;"><span class="status-pill">{success_count} {"совпадений" if lang == "ru" else "matches"}</span>'
        f'<span class="status-pill {"fail" if failed_count else ""}">{failed_count} {"без совпадения" if lang == "ru" else "no match"}</span></div>'
        "</div>"
        '<div class="table-wrap"><table><thead><tr>'
        f"<th>{'Запрос' if lang == 'ru' else 'Query'}</th><th>{'Источник' if lang == 'ru' else 'Source'}</th><th>{'Каталожный номер' if lang == 'ru' else 'Catalogue Number'}</th><th>{'Название' if lang == 'ru' else 'Product Name'}</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></section>"
    )


@app.get("/", response_class=HTMLResponse)
def landing_page(lang: str = "ru") -> HTMLResponse:
    lang = _normalize_lang(lang)
    copy = {
        "ru": {
            "tag": "Панель",
            "title": "Выберите режим",
            "subtitle": "Загрузка по коду или поиск кодов по названию.",
            "download_title": "Загрузка документов",
            "download_text": "Пакетная загрузка COA, MSDS и COO по каталожным номерам.",
            "download_button": "Открыть",
            "lookup_title": "Поиск кодов",
            "lookup_text": "Поиск каталожных номеров по названиям продуктов.",
            "lookup_button": "Открыть",
        },
        "en": {
            "tag": "Panel",
            "title": "Choose mode",
            "subtitle": "Download by code or look up codes by name.",
            "download_title": "Document Download",
            "download_text": "Batch download COA, MSDS, and COO by catalogue number.",
            "download_button": "Open",
            "lookup_title": "Code Lookup",
            "lookup_text": "Find catalogue numbers by product name.",
            "lookup_button": "Open",
        },
    }[lang]
    body = f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">{copy["tag"]}</span>
      <h1>{copy["title"]}</h1>
      <p class="lede">{copy["subtitle"]}</p>
      <div class="hero-actions">
        <a class="button" href="{_with_lang('/download', lang)}">{copy["download_button"]}</a>
        <a class="button ghost" href="{_with_lang('/lookup', lang)}">{copy["lookup_button"]}</a>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>edqmUSP</h3>
      <ul>
        <li>EDQM</li>
        <li>USP</li>
        <li>ZIP</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="grid">
    <section class="card">
      <h2>{copy["download_title"]}</h2>
      <p class="muted">{copy["download_text"]}</p>
      <a class="button" style="margin-top:16px;" href="{_with_lang('/download', lang)}">{copy["download_button"]}</a>
    </section>
    <section class="card">
      <h2>{copy["lookup_title"]}</h2>
      <p class="muted">{copy["lookup_text"]}</p>
      <a class="button secondary" style="margin-top:16px;" href="{_with_lang('/lookup', lang)}">{copy["lookup_button"]}</a>
    </section>
  </div>
</section>
"""
    return _page("edqmUSP", body, active="home", lang=lang)


async def _handle_vercel_entry(request: Request):
    page = (request.query_params.get("page") or "home").lower()
    lang = _normalize_lang(request.query_params.get("lang"))
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
            return download_page(lang=lang)
        if page == "lookup":
            return lookup_page(lang=lang)
        return landing_page(lang=lang)

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
        lang = _normalize_lang(form_first("lang", lang))
        return download_documents(source=source, codes=codes, doc_types=doc_types, lang=lang)

    if page == "lookup":
        source = form_first("source", "both")
        names = form_first("names", "")
        lang = _normalize_lang(form_first("lang", lang))
        return lookup_catalogue_numbers(source=source, names=names, lang=lang)

    return landing_page(lang=lang)


@app.get("/download", response_class=HTMLResponse)
def download_page(lang: str = "ru") -> HTMLResponse:
    lang = _normalize_lang(lang)
    title = "Загрузка" if lang == "ru" else "Download"
    return _page(title, _download_form(lang=lang), active="download", lang=lang)


@app.post("/download")
def download_documents(
    source: str = Form(...),
    codes: str = Form(""),
    doc_types: list[str] = Form(default_factory=list),
    lang: str = Form("ru"),
):
    lang = _normalize_lang(lang)
    source = source.lower().strip()
    clean_codes = _parse_lines(codes)
    clean_doc_types = [doc.upper() for doc in doc_types if doc.upper() in {"COA", "MSDS", "COO"}]
    title = "Загрузка" if lang == "ru" else "Download"
    invalid_source = "Неверный источник." if lang == "ru" else "Invalid source."
    need_codes = "Введите хотя бы один каталожный номер." if lang == "ru" else "Enter at least one catalogue number."
    need_docs = "Выберите хотя бы один тип документа." if lang == "ru" else "Select at least one document type."
    failed_message = "Ошибка загрузки" if lang == "ru" else "Download failed"
    no_files = "Файлы не скачаны. См. манифест ниже." if lang == "ru" else "No files were downloaded. See the manifest below."
    manifest_title = "Манифест" if lang == "ru" else "Manifest"

    if source not in {"edqm", "usp"}:
        return _page(
            title,
            _download_form(source="edqm", codes=codes, message=invalid_source, selected_docs=clean_doc_types, lang=lang),
            active="download",
            lang=lang,
        )
    if not clean_codes:
        return _page(
            title,
            _download_form(source=source, codes=codes, message=need_codes, selected_docs=clean_doc_types, lang=lang),
            active="download",
            lang=lang,
        )
    if not clean_doc_types:
        return _page(
            title,
            _download_form(source=source, codes=codes, message=need_docs, selected_docs=[], lang=lang),
            active="download",
            lang=lang,
        )

    try:
        batch_zip, manifest_text, position_count = _download_batch(source, clean_codes, clean_doc_types)
    except Exception as exc:
        body = _download_form(
            source=source,
            codes=codes,
            message=f"{failed_message}: {exc}",
            selected_docs=clean_doc_types,
            lang=lang,
        )
        return _page(title, body, active="download", lang=lang)

    if not batch_zip:
        body = (
            _download_form(
                source=source,
                codes=codes,
                message=no_files,
                selected_docs=clean_doc_types,
                lang=lang,
            )
            + f'<section class="manifest-panel"><h3>{manifest_title}</h3><pre>{_safe_text(manifest_text)}</pre></section>'
        )
        return _page(title, body, active="download", lang=lang)

    filename = f"{source.upper()}_BATCH_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{position_count}pos.zip"
    return StreamingResponse(
        BytesIO(batch_zip),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/lookup", response_class=HTMLResponse)
def lookup_page(lang: str = "ru") -> HTMLResponse:
    lang = _normalize_lang(lang)
    title = "Поиск кодов" if lang == "ru" else "Lookup"
    return _page(title, _lookup_form(lang=lang), active="lookup", lang=lang)


@app.post("/lookup", response_class=HTMLResponse)
def lookup_catalogue_numbers(
    source: str = Form("both"),
    names: str = Form(""),
    lang: str = Form("ru"),
):
    lang = _normalize_lang(lang)
    title = "Поиск кодов" if lang == "ru" else "Lookup"
    clean_names = _parse_lines(names)
    if not clean_names:
        return _page(
            title,
            _lookup_form(
                source=source,
                names=names,
                message="Введите хотя бы одно название." if lang == "ru" else "Enter at least one product name.",
                lang=lang,
            ),
            active="lookup",
            lang=lang,
        )

    try:
        rows = _lookup_catalogue_numbers(source, clean_names)
    except Exception as exc:
        return _page(
            title,
            _lookup_form(
                source=source,
                names=names,
                message=f"{'Ошибка поиска' if lang == 'ru' else 'Lookup failed'}: {exc}",
                lang=lang,
            ),
            active="lookup",
            lang=lang,
        )

    table_html = _lookup_results_table(rows, lang=lang)
    return _page(
        title,
        _lookup_form(source=source, names=names, table_html=table_html, lang=lang),
        active="lookup",
        lang=lang,
    )


@app.get("/health", response_class=PlainTextResponse)
def healthcheck() -> str:
    return "ok"


@app.api_route("/api/index.py", methods=["GET", "POST"])
async def vercel_index_entry(request: Request):
    return await _handle_vercel_entry(request)
