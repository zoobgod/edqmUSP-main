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
try:  # Prefer normal import resolution; only patch sys.path if the runtime needs it.
    import src  # type: ignore # noqa: F401
except Exception:  # pragma: no cover
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

app = FastAPI(title="edqmUSP")

# Optional shared services. If another worker extracts helpers into src/services,
# this frontend will adopt them automatically without changing route behavior.
try:
    from src.services import bundles as _bundles_service
except Exception:  # pragma: no cover
    _bundles_service = None

try:
    from src.services import lookup as _lookup_service
except Exception:  # pragma: no cover
    _lookup_service = None

APP_CSS = """
<style>
:root {
  --paper: #e8edf7;
  --paper-2: #f5f8ff;
  --ink: #121826;
  --muted: #5f6f89;
  --muted-2: #72839d;
  --card: rgba(255, 255, 255, 0.86);
  --line: rgba(45, 70, 107, 0.18);
  --line-strong: rgba(45, 70, 107, 0.34);
  --teal: #1f58c3;
  --teal-2: #2d7cff;
  --teal-soft: rgba(45, 124, 255, 0.14);
  --bronze: #0f1729;
  --bronze-2: #243a63;
  --rose: #d1495b;
  --shadow: 0 24px 64px rgba(15, 29, 62, 0.14);
  --shadow-soft: 0 10px 30px rgba(15, 29, 62, 0.09);
  --radius-xl: 28px;
  --radius-lg: 20px;
  --radius-md: 16px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 12% 12%, rgba(45,124,255,0.26), transparent 24%),
    radial-gradient(circle at 82% 10%, rgba(64,152,255,0.16), transparent 28%),
    radial-gradient(circle at 80% 75%, rgba(31,88,195,0.09), transparent 18%),
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
  background: linear-gradient(135deg, rgba(13, 23, 43, 0.94), rgba(24, 44, 79, 0.92));
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
  color: rgba(210, 223, 247, 0.86);
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
  color: #e8f1ff;
  text-decoration: none;
  padding: 10px 16px;
  border: 1px solid rgba(146, 176, 228, 0.22);
  border-radius: 999px;
  background: rgba(255,255,255,0.06);
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease;
}
.nav a:hover {
  transform: translateY(-1px);
  border-color: rgba(146, 176, 228, 0.48);
  background: rgba(255,255,255,0.14);
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
  background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(248,252,255,0.84));
  box-shadow: var(--shadow);
}
.hero-shell {
  overflow: hidden;
  padding: 34px;
  border-radius: var(--radius-xl);
  color: #e8f1ff;
  background:
    radial-gradient(circle at 7% 10%, rgba(88, 167, 255, 0.25), transparent 32%),
    radial-gradient(circle at 88% 14%, rgba(77, 142, 255, 0.3), transparent 36%),
    linear-gradient(135deg, #0d1730, #182c4f);
}
.hero-shell::after {
  content: "";
  position: absolute;
  top: -90px;
  right: -60px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(130,190,255,0.15), rgba(130,190,255,0.01) 62%, transparent 70%);
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
  color: rgba(218, 232, 255, 0.9);
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
    linear-gradient(180deg, rgba(102, 174, 255, 0.16), rgba(255,255,255,0.04)),
    rgba(255,255,255,0.04);
  border: 1px solid rgba(146, 176, 228, 0.24);
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
  background: linear-gradient(135deg, #8fcbff, #5f9bff);
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
.copy-tools {
  display: grid;
  gap: 14px;
  margin-bottom: 18px;
}
.copy-meta {
  color: var(--muted);
  font-size: 0.9rem;
}
.copy-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.copy-box {
  width: 100%;
  min-height: 132px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.88);
  color: var(--ink);
  font: inherit;
  font-family: "SFMono-Regular", "Consolas", "Liberation Mono", monospace;
  line-height: 1.5;
  resize: vertical;
}
.copy-box.compact {
  min-height: 92px;
}
.table-code {
  font-family: "SFMono-Regular", "Consolas", "Liberation Mono", monospace;
  font-weight: 700;
  letter-spacing: 0.01em;
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
  background: rgba(45, 124, 255, 0.12);
  color: #1f58c3;
  border: 1px solid rgba(45, 124, 255, 0.22);
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
.task-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
}
.task-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(146, 176, 228, 0.34);
  background: rgba(255, 255, 255, 0.08);
  font-size: 0.82rem;
  color: rgba(232, 241, 255, 0.95);
}
.task-pill b {
  color: #9ec8ff;
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

APP_SCRIPT = """
<script>
function copyFromTextarea(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.focus();
  el.select();
  el.setSelectionRange(0, el.value.length);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(el.value).catch(() => document.execCommand('copy'));
    return;
  }
  document.execCommand('copy');
}
</script>
"""


def _page(title: str, body: str, active: str = "") -> HTMLResponse:
    nav_items = [
        ("/", "Home", "home"),
        ("/download", "Download Documents", "download"),
        ("/lookup", "Find Catalogue Numbers", "lookup"),
        ("/batches", "Current Batch Numbers", "batches"),
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
    {APP_SCRIPT}
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


def _service_call(module, names: tuple[str, ...], *args, **kwargs):
    if module is None:
        return None
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn(*args, **kwargs)
    return None


def _parse_vercel_form(raw_body: bytes) -> dict[str, list[str]]:
    return parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)


def _parse_lines(raw: str) -> list[str]:
    values: list[str] = []
    for piece in re.split(r"[\r\n;]+", raw or ""):
        item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", piece).strip()
        if item:
            values.append(item)
    return values


def _clean_lookup_fragment(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"\([^)]*(?:edqm|usp)[^)]*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]*(?:edqm|usp)[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-|]\s*(?:edqm|usp)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-_/|,;")
    return text


def _strip_lookup_suffix_tokens(value: str) -> str:
    tokens = [token for token in re.split(r"\s+", value or "") if token]
    while tokens and tokens[-1].rstrip(".,").upper() in {"RS", "CRS"}:
        tokens.pop()
    return " ".join(tokens).strip()


def _strip_lookup_quantity_tokens(value: str) -> str:
    text = value or ""
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|kg|mcg|ug|μg|ml|l|mmol|mol|ppm|%)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b\d+(?:[.,]\d+)?\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-_/|,;")
    return text


def _prefix_lookup_candidates(value: str, min_words: int = 2, max_words: int = 5) -> list[str]:
    words = [word for word in re.split(r"\s+", value or "") if word]
    if len(words) < min_words:
        return []

    upper_bound = min(len(words), max_words)
    prefixes: list[str] = []
    for size in range(upper_bound, min_words - 1, -1):
        prefix = " ".join(words[:size]).strip()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _lookup_query_candidates(raw_query: str) -> list[str]:
    shared = _service_call(
        _lookup_service,
        (
            "lookup_query_candidates",
            "build_lookup_candidates",
            "generate_lookup_candidates",
        ),
        raw_query,
    )
    if isinstance(shared, list):
        return [str(item) for item in shared if str(item).strip()]

    base = _clean_lookup_fragment(raw_query)
    if not base:
        return []

    split_parts = re.split(r"\s*[/|;]\s*", base)
    candidates: list[str] = []

    def add(value: str):
        cleaned = _clean_lookup_fragment(value)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
        stripped = _strip_lookup_suffix_tokens(cleaned)
        if stripped and stripped not in candidates:
            candidates.append(stripped)
        quantity_stripped = _strip_lookup_quantity_tokens(stripped or cleaned)
        if quantity_stripped and quantity_stripped not in candidates:
            candidates.append(quantity_stripped)
        for prefix in _prefix_lookup_candidates(quantity_stripped or stripped or cleaned):
            if prefix not in candidates:
                candidates.append(prefix)

    latin_parts = [part for part in split_parts if re.search(r"[A-Za-z]", part or "")]
    for part in latin_parts:
        add(part)

    add(base)

    for part in split_parts:
        add(part)

    if not candidates:
        add(raw_query)

    return candidates


def _search_lookup_candidates(downloader, raw_query: str, limit: int = 8) -> tuple[list, str]:
    shared = _service_call(
        _lookup_service,
        (
            "search_lookup_candidates",
            "search_candidates",
        ),
        downloader,
        raw_query,
        limit,
    )
    if isinstance(shared, tuple) and len(shared) == 2:
        return shared

    attempted: list[str] = []
    for candidate in _lookup_query_candidates(raw_query):
        attempted.append(candidate)
        matches = downloader.search_products_by_name(candidate, limit=limit)
        if matches:
            return matches, candidate
    fallback = attempted[0] if attempted else raw_query.strip()
    return [], fallback


def _bundle_name(source: str, code: str, position_name: str) -> str:
    shared = _service_call(
        _bundles_service,
        (
            "bundle_name",
            "build_bundle_name",
        ),
        source,
        code,
        position_name,
    )
    if isinstance(shared, str) and shared.strip():
        return shared
    return f"{source.upper()}_{code}_{position_name}".strip()


def _zip_member_name(bundle_name: str, doc_type: str, file_path: Path) -> str:
    shared = _service_call(
        _bundles_service,
        (
            "zip_member_name",
            "build_zip_member_name",
        ),
        bundle_name,
        doc_type,
        file_path,
    )
    if isinstance(shared, str) and shared.strip():
        return shared
    if doc_type == "COO":
        return file_path.name
    suffix = file_path.suffix.lower() or ".pdf"
    return f"{_safe_filename(bundle_name)}_{doc_type}{suffix}"


def _build_position_zip(bundle_name: str, files_by_doc: dict[str, Path]) -> bytes:
    shared = _service_call(
        _bundles_service,
        (
            "build_position_zip",
            "position_zip_bytes",
        ),
        bundle_name,
        files_by_doc,
    )
    if isinstance(shared, (bytes, bytearray)):
        return bytes(shared)

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
    shared = _service_call(
        _bundles_service,
        (
            "build_batch_zip",
            "batch_zip_bytes",
        ),
        source,
        successful_files,
        position_names,
        manifest_text,
    )
    if isinstance(shared, (bytes, bytearray)):
        return bytes(shared)

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
    shared = _service_call(
        _bundles_service,
        (
            "resolve_position_name",
            "get_position_name",
        ),
        downloader,
        code,
    )
    if isinstance(shared, str) and shared.strip():
        return shared

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
                    matches, _used_candidate = _search_lookup_candidates(downloader, query, limit=limit)
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
                    matches, _used_candidate = _search_lookup_candidates(downloader, query, limit=limit)
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


def _lookup_current_batches(source: str, codes: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source = source.lower()

    if source == "edqm":
        from src.downloaders.edqm import EDQMDownloader as DownloaderCls
    else:
        from src.downloaders.usp import USPDownloader as DownloaderCls

    with TemporaryDirectory() as tmpdir:
        downloader = DownloaderCls(download_dir=Path(tmpdir))
        downloader.start()
        try:
            for code in codes:
                if not downloader.search_product(code):
                    rows.append(
                        {
                            "query": code,
                            "source": source.upper(),
                            "code": code,
                            "name": "",
                            "batch_number": "",
                            "status": "Product not found",
                        }
                    )
                    continue

                position_name = _resolve_position_name(downloader, code)
                getter = getattr(downloader, "get_current_batch_number", None)
                batch_number = ""
                if callable(getter):
                    try:
                        batch_number = (getter(code) or "").strip()
                    except Exception:
                        batch_number = ""

                rows.append(
                    {
                        "query": code,
                        "source": source.upper(),
                        "code": code,
                        "name": position_name,
                        "batch_number": batch_number,
                        "status": "OK" if batch_number else "Batch not found",
                    }
                )
        finally:
            downloader.stop()

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
      <span class="eyebrow">Download</span>
      <h1>Batch download by catalogue code.</h1>
      <p class="lede">Choose source, paste codes, download one batch ZIP.</p>
      <div class="task-strip">
        <span class="task-pill"><b>1</b> Select source</span>
        <span class="task-pill"><b>2</b> Paste codes</span>
        <span class="task-pill"><b>3</b> Download ZIP</span>
      </div>
      {note}
      <div class="hero-stats">
        <div class="grid">
          <div class="stat">
            <span class="stat-value">COA / MSDS / COO</span>
            <span class="stat-label">Select any combination</span>
          </div>
          <div class="stat">
            <span class="stat-value">Nested ZIP</span>
            <span class="stat-label">One position ZIP per code</span>
          </div>
          <div class="stat">
            <span class="stat-value">Manifest included</span>
            <span class="stat-label">Shows missing documents per code</span>
          </div>
        </div>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>Quick rules</h3>
      <ul>
        <li>Run one source at a time: EDQM or USP.</li>
        <li>Use one code per line.</li>
        <li>If a file is missing, check the manifest section.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=download" class="panel">
      <h2>Batch Input</h2>
      <p class="muted">Task-first mode: minimal input, direct output.</p>

      <div class="field-group">
        <label for="source">1) Source</label>
        <div class="field-hint">Choose the catalogue family.</div>
        <select id="source" name="source">
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="codes">2) Catalogue numbers</label>
        <div class="field-hint">Paste one code per line.</div>
        <textarea id="codes" name="codes" placeholder="Y0001532&#10;G0400006&#10;1134357">{_safe_text(codes)}</textarea>
      </div>

      <div class="field-group">
        <label>3) Documents</label>
        <div class="field-hint">Select what should be included in the ZIP.</div>
        <div class="checks">
          <label><input type="checkbox" name="doc_types" value="COA" {checked("COA")}> COA</label>
          <label><input type="checkbox" name="doc_types" value="MSDS" {checked("MSDS")}> MSDS</label>
          <label><input type="checkbox" name="doc_types" value="COO" {checked("COO")}> COO</label>
        </div>
      </div>

      <button type="submit">Generate ZIP</button>
      <div class="microcopy" style="margin-top: 12px;">The download starts immediately after processing.</div>
    </form>

    <aside class="panel section-stack">
      <div>
        <h3>Notes</h3>
        <ul class="mini-list">
          <li>Keep source and codes consistent.</li>
          <li>Manifest shows exact failures per document type.</li>
          <li>You can re-run quickly with edited code list.</li>
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
      <span class="eyebrow">Lookup</span>
      <h1>Find catalogue numbers from product names.</h1>
      <p class="lede">Paste messy lines, get usable EDQM/USP codes.</p>
      <div class="task-strip">
        <span class="task-pill"><b>1</b> Paste names</span>
        <span class="task-pill"><b>2</b> Run lookup</span>
        <span class="task-pill"><b>3</b> Copy code column</span>
      </div>
      {note}
      <div class="hero-actions">
        <a class="button secondary" href="/download">Open downloader</a>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>Lookup behavior</h3>
      <ul>
        <li>Tries cleaned variants of each line.</li>
        <li>Supports combined strings with slashes and notes.</li>
        <li>Returns closest matches by source.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=lookup" class="panel">
      <h2>Lookup Input</h2>
      <p class="muted">Bulk input optimized for copied task lists.</p>

      <div class="field-group">
        <label for="source">1) Source</label>
        <div class="field-hint">Use both if unknown.</div>
        <select id="source" name="source">
          <option value="both" {"selected" if source == "both" else ""}>Both</option>
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="names">2) Product names</label>
        <div class="field-hint">One line per item. Mixed-language lines are supported.</div>
        <textarea id="names" name="names" placeholder="PICOTAMIDE MONOHYDRATE CRS&#10;Cisplatin&#10;Glycerol Monostearate 40-55 CRS">{_safe_text(names)}</textarea>
      </div>

      <button type="submit" class="secondary">Run Lookup</button>
    </form>

    <aside class="panel section-stack">
      <div>
        <h3>Examples</h3>
        <ul class="mini-list">
          <li><code>Raltegravir Impurity E RS / ... (EDQM)</code></li>
          <li><code>Sodium taurocholate BRP 10000 mg / ...</code></li>
          <li><code>Cisplatin</code></li>
        </ul>
      </div>
    </aside>
  </div>
  {table_html}
</section>
"""


def _batch_lookup_form(source: str = "edqm", codes: str = "", table_html: str = "", message: str = "") -> str:
    source = source.lower().strip()
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="hero-shell">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">Batch Lookup</span>
      <h1>Get current batch numbers by catalogue code.</h1>
      <p class="lede">Paste one code per line and return the current EDQM batch number or the current USP lot number.</p>
      <div class="task-strip">
        <span class="task-pill"><b>1</b> Select source</span>
        <span class="task-pill"><b>2</b> Paste codes</span>
        <span class="task-pill"><b>3</b> Copy batch column</span>
      </div>
      {note}
      <div class="hero-actions">
        <a class="button secondary" href="/download">Open downloader</a>
        <a class="button ghost" href="/lookup">Open catalogue finder</a>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>Batch source</h3>
      <ul>
        <li>EDQM: reads the current batch number from the detailed product page.</li>
        <li>USP: reads the current lot number from the batch table.</li>
        <li>Returns one result row per input code.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="form-grid">
    <form method="post" action="/api/index.py?page=batches" class="panel">
      <h2>Batch Input</h2>
      <p class="muted">Bulk mode for current batch checks.</p>

      <div class="field-group">
        <label for="source">1) Source</label>
        <div class="field-hint">Choose one source at a time.</div>
        <select id="source" name="source">
          <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
          <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
        </select>
      </div>

      <div class="field-group">
        <label for="codes">2) Catalogue numbers</label>
        <div class="field-hint">Paste one code per line.</div>
        <textarea id="codes" name="codes" placeholder="I0020000&#10;Y0001532&#10;1335508">{_safe_text(codes)}</textarea>
      </div>

      <button type="submit" class="secondary">Run Batch Lookup</button>
    </form>

    <aside class="panel section-stack">
      <div>
        <h3>Output</h3>
        <ul class="mini-list">
          <li>Copy the whole batch column in one action.</li>
          <li>Use the table view to review code and product name together.</li>
          <li>Re-run quickly after editing only the missing lines.</li>
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
    catalogue_numbers = [row["code"] for row in rows if row["code"]]
    unique_codes = list(dict.fromkeys(catalogue_numbers))
    code_column = "\n".join(catalogue_numbers)
    unique_code_column = "\n".join(unique_codes)
    tsv_rows = ["Query\tSource\tCatalogue Number\tProduct Name"]
    for row in rows:
        tsv_rows.append(
            "\t".join(
                [
                    row["query"],
                    row["source"],
                    row["code"],
                    row["name"],
                ]
            )
        )
    tsv_text = "\n".join(tsv_rows)
    body = []
    for row in rows:
        status = row["code"] if row["code"] else "No match"
        klass = "status-ok" if row["code"] else "status-fail"
        body.append(
            "<tr>"
            f"<td>{_safe_text(row['query'])}</td>"
            f"<td>{_safe_text(row['source'])}</td>"
            f'<td class="{klass} table-code">{_safe_text(status)}</td>'
            f"<td>{_safe_text(row['name'])}</td>"
            "</tr>"
        )
    return (
        '<section class="table-panel">'
        '<div class="table-header">'
        '<div><h3>Lookup Results</h3><p class="muted">Task-ready output for copy/paste into your next step.</p></div>'
        f'<div style="display:flex; gap:10px; flex-wrap:wrap;"><span class="status-pill">{success_count} matches</span>'
        f'<span class="status-pill {"fail" if failed_count else ""}">{failed_count} no-match rows</span></div>'
        "</div>"
        '<div class="copy-tools">'
        f'<div class="copy-meta">{len(unique_codes)} unique catalogue numbers</div>'
        '<div class="copy-actions">'
        '<button type="button" class="button" onclick="copyFromTextarea(\'catalogue-copy-box\')">Copy Catalogue Numbers</button>'
        '<button type="button" class="button secondary" onclick="copyFromTextarea(\'catalogue-copy-unique\')">Copy Unique Codes</button>'
        '<button type="button" class="button secondary" onclick="copyFromTextarea(\'catalogue-copy-tsv\')">Copy Table TSV</button>'
        '</div>'
        f'<textarea id="catalogue-copy-box" class="copy-box compact" readonly>{_safe_text(code_column)}</textarea>'
        f'<textarea id="catalogue-copy-unique" class="copy-box compact" readonly>{_safe_text(unique_code_column)}</textarea>'
        f'<textarea id="catalogue-copy-tsv" class="copy-box" readonly style="min-height: 180px;">{_safe_text(tsv_text)}</textarea>'
        '</div>'
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Query</th><th>Source</th><th>Catalogue Number</th><th>Product Name</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></section>"
    )


def _batch_results_table(rows: list[dict[str, str]]) -> str:
    found_count = sum(1 for row in rows if row["batch_number"])
    missing_count = len(rows) - found_count
    batch_numbers = [row["batch_number"] for row in rows if row["batch_number"]]
    unique_batches = list(dict.fromkeys(batch_numbers))
    batch_column = "\n".join(batch_numbers)
    unique_batch_column = "\n".join(unique_batches)
    tsv_rows = ["Input\tSource\tCatalogue Number\tProduct Name\tCurrent Batch Number"]
    body = []

    for row in rows:
        rendered_batch = row["batch_number"] or row["status"]
        tsv_rows.append(
            "\t".join(
                [
                    row["query"],
                    row["source"],
                    row["code"],
                    row["name"],
                    rendered_batch,
                ]
            )
        )
        klass = "status-ok" if row["batch_number"] else "status-fail"
        body.append(
            "<tr>"
            f"<td>{_safe_text(row['query'])}</td>"
            f"<td>{_safe_text(row['source'])}</td>"
            f'<td class="table-code">{_safe_text(row["code"])}</td>'
            f"<td>{_safe_text(row['name'])}</td>"
            f'<td class="{klass} table-code">{_safe_text(rendered_batch)}</td>'
            "</tr>"
        )

    tsv_text = "\n".join(tsv_rows)
    return (
        '<section class="table-panel">'
        '<div class="table-header">'
        '<div><h3>Current Batch Results</h3><p class="muted">Copy-ready output for batch release checks.</p></div>'
        f'<div style="display:flex; gap:10px; flex-wrap:wrap;"><span class="status-pill">{found_count} batches found</span>'
        f'<span class="status-pill {"fail" if missing_count else ""}">{missing_count} missing</span></div>'
        "</div>"
        '<div class="copy-tools">'
        f'<div class="copy-meta">{len(unique_batches)} unique current batch numbers</div>'
        '<div class="copy-actions">'
        '<button type="button" class="button" onclick="copyFromTextarea(\'batch-copy-box\')">Copy Batch Numbers</button>'
        '<button type="button" class="button secondary" onclick="copyFromTextarea(\'batch-copy-unique\')">Copy Unique Batch Numbers</button>'
        '<button type="button" class="button secondary" onclick="copyFromTextarea(\'batch-copy-tsv\')">Copy Table TSV</button>'
        '</div>'
        f'<textarea id="batch-copy-box" class="copy-box compact" readonly>{_safe_text(batch_column)}</textarea>'
        f'<textarea id="batch-copy-unique" class="copy-box compact" readonly>{_safe_text(unique_batch_column)}</textarea>'
        f'<textarea id="batch-copy-tsv" class="copy-box" readonly style="min-height: 180px;">{_safe_text(tsv_text)}</textarea>'
        '</div>'
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Input</th><th>Source</th><th>Catalogue Number</th><th>Product Name</th><th>Current Batch Number</th>"
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
      <span class="eyebrow">edqmUSP</span>
      <h1>Three focused workflows.</h1>
      <p class="lede">Use lookup for names, download for documents, and batches for current batch numbers.</p>
      <div class="task-strip">
        <span class="task-pill"><b>Lookup</b> Names -> Codes</span>
        <span class="task-pill"><b>Download</b> Codes -> Documents</span>
        <span class="task-pill"><b>Batches</b> Codes -> Current Batch</span>
      </div>
      <div class="hero-actions">
        <a class="button" href="/download">Open Downloader</a>
        <a class="button ghost" href="/lookup">Find Catalogue Numbers</a>
        <a class="button secondary" href="/batches">Open Batch Lookup</a>
      </div>
      <div class="hero-stats">
        <div class="grid">
          <div class="stat">
            <span class="stat-value">EDQM + USP</span>
            <span class="stat-label">Both public sources supported</span>
          </div>
          <div class="stat">
            <span class="stat-value">Bulk input</span>
            <span class="stat-label">One line per name or code</span>
          </div>
          <div class="stat">
            <span class="stat-value">Copy-ready output</span>
            <span class="stat-label">Column copy and TSV copy for fast handoff</span>
          </div>
          <div class="stat">
            <span class="stat-value">Current batches</span>
            <span class="stat-label">EDQM batch and USP current lot lookup</span>
          </div>
        </div>
      </div>
    </div>
    <aside class="hero-aside">
      <h3>Execution model</h3>
      <ul>
        <li>No auth flow for EDQM/USP public endpoints.</li>
        <li>Download step returns one batch ZIP.</li>
        <li>Lookup step tolerates noisy input lines.</li>
        <li>Batch step returns the current EDQM or USP batch value.</li>
      </ul>
    </aside>
  </div>
</section>

<section class="surface">
  <div class="grid">
    <section class="card">
      <h2>Download Documents</h2>
      <p class="muted">Use when you already have catalogue numbers.</p>
      <ul class="feature-list" style="display:grid; gap:10px; margin:16px 0 18px;">
        <li>Choose COA, MSDS, COO.</li>
        <li>Position-level nested ZIP bundles.</li>
        <li>Manifest for missing documents.</li>
      </ul>
      <a class="button" href="/download">Open Downloader</a>
    </section>
    <section class="card">
      <h2>Find Catalogue Numbers</h2>
      <p class="muted">Use when you only have product names.</p>
      <ul class="feature-list" style="display:grid; gap:10px; margin:16px 0 18px;">
        <li>Cross-search EDQM, USP, or both.</li>
        <li>Input cleanup for mixed/noisy strings.</li>
        <li>Copy catalogue column in one click.</li>
      </ul>
      <a class="button secondary" href="/lookup">Open Catalogue Finder</a>
    </section>
    <section class="card">
      <h2>Current Batch Numbers</h2>
      <p class="muted">Use when you already have catalogue numbers and need the current batch.</p>
      <ul class="feature-list" style="display:grid; gap:10px; margin:16px 0 18px;">
        <li>One line per code.</li>
        <li>EDQM and USP supported.</li>
        <li>Copy-ready batch number column.</li>
      </ul>
      <a class="button ghost" href="/batches">Open Batch Lookup</a>
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
    elif path.endswith("/batches"):
        page = "batches"
    elif path.endswith("/health"):
        page = "health"

    if page == "health":
        return PlainTextResponse("ok")

    if request.method == "GET":
        if page == "download":
            return download_page()
        if page == "lookup":
            return lookup_page()
        if page == "batches":
            return batch_lookup_page()
        return landing_page()

    raw_body = await request.body()
    parsed_form = _parse_vercel_form(raw_body)

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

    if page == "batches":
        source = form_first("source", "edqm")
        codes = form_first("codes", "")
        return current_batch_lookup(source=source, codes=codes)

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


@app.get("/batches", response_class=HTMLResponse)
def batch_lookup_page() -> HTMLResponse:
    return _page("Current Batch Numbers", _batch_lookup_form(), active="batches")


@app.post("/batches", response_class=HTMLResponse)
def current_batch_lookup(
    source: str = Form("edqm"),
    codes: str = Form(""),
):
    source = source.lower().strip()
    clean_codes = _parse_lines(codes)

    if source not in {"edqm", "usp"}:
        return _page(
            "Current Batch Numbers",
            _batch_lookup_form(source="edqm", codes=codes, message="Invalid source."),
            active="batches",
        )

    if not clean_codes:
        return _page(
            "Current Batch Numbers",
            _batch_lookup_form(source=source, codes=codes, message="Enter at least one catalogue number."),
            active="batches",
        )

    try:
        rows = _lookup_current_batches(source, clean_codes)
    except Exception as exc:
        return _page(
            "Current Batch Numbers",
            _batch_lookup_form(source=source, codes=codes, message=f"Batch lookup failed: {exc}"),
            active="batches",
        )

    table_html = _batch_results_table(rows)
    return _page(
        "Current Batch Numbers",
        _batch_lookup_form(source=source, codes=codes, table_html=table_html),
        active="batches",
    )


@app.get("/health", response_class=PlainTextResponse)
def healthcheck() -> str:
    return "ok"


@app.api_route("/api/index.py", methods=["GET", "POST"])
async def vercel_index_entry(request: Request):
    return await _handle_vercel_entry(request)
