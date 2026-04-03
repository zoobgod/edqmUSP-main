"""Vercel-compatible ASGI frontend for edqmUSP."""

from __future__ import annotations

import html
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:  # Prefer normal import resolution; only patch sys.path if the runtime needs it.
    import src  # type: ignore # noqa: F401
except Exception:  # pragma: no cover
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from src.services.bundles import (
    build_batch_zip as _svc_build_batch_zip,
    build_position_zip as _svc_build_position_zip,
    bundle_name as _svc_bundle_name,
    resolve_position_name as _svc_resolve_position_name,
    safe_file_part as _svc_safe_file_part,
    zip_member_name as _svc_zip_member_name,
)
from src.services.cas import (
    append_cas_to_position_name as _svc_append_cas_to_position_name,
    resolve_cas_number as _svc_resolve_cas_number,
)
from src.services.lookup import (
    lookup_query_candidates as _svc_lookup_query_candidates,
    search_lookup_candidates as _svc_search_lookup_candidates,
)

app = FastAPI(title="edqmUSP")
DOWNLOAD_CACHE_TTL_SECONDS = 900
DOWNLOAD_CACHE_MAX_ENTRIES = 20
_DOWNLOAD_CACHE: dict[str, dict[str, object]] = {}

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
  --primary: #1f58c3;
  --primary-light: #2d7cff;
  --primary-soft: rgba(45, 124, 255, 0.14);
  --dark: #0f1729;
  --dark-2: #243a63;
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
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
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
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
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
  grid-template-columns: minmax(0, 1.2fr) minmax(220px, 0.8fr);
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
  color: var(--primary);
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
  background: linear-gradient(135deg, var(--primary-light), var(--dark-2));
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
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
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
  background: linear-gradient(135deg, var(--dark), var(--dark-2));
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
  accent-color: var(--primary);
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
.lookup-details {
  min-width: 240px;
}
.lookup-details summary {
  cursor: pointer;
  font-weight: 700;
  color: var(--primary);
}
.lookup-detail-grid {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}
.lookup-detail-item {
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: rgba(17, 32, 57, 0.04);
}
.lookup-detail-item b {
  display: block;
  margin-bottom: 4px;
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
.result-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.timeline-grid {
  display: grid;
  gap: 16px;
}
.timeline-card {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255,255,255,0.84);
  box-shadow: var(--shadow-soft);
  padding: 18px;
}
.timeline-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.timeline-card-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.step-list.inline {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.step-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(17, 32, 57, 0.05);
  font-size: 0.92rem;
}
.step-pill.ok {
  border-color: rgba(31, 88, 195, 0.18);
  background: rgba(45, 124, 255, 0.1);
  color: #163c8c;
}
.step-pill.fail {
  border-color: rgba(209, 73, 91, 0.22);
  background: rgba(209, 73, 91, 0.08);
  color: #96273a;
}
.step-pill.neutral {
  color: var(--muted);
}
.notes-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}
.note-item {
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: rgba(17, 32, 57, 0.04);
}
.doc-status {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.doc-status.ok {
  color: #163c8c;
}
.doc-status.fail {
  color: #96273a;
}
.wrap-cell {
  white-space: normal;
  min-width: 180px;
}
.action-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(17, 32, 57, 0.05);
  font-weight: 700;
}
.action-pill.ok {
  color: #163c8c;
  border-color: rgba(31, 88, 195, 0.2);
  background: rgba(45, 124, 255, 0.1);
}
.action-pill.warn {
  color: #8a5a13;
  border-color: rgba(201, 139, 60, 0.25);
  background: rgba(201, 139, 60, 0.12);
}
.action-pill.fail {
  color: #96273a;
  border-color: rgba(209, 73, 91, 0.22);
  background: rgba(209, 73, 91, 0.08);
}
.table-link {
  color: var(--primary);
  font-weight: 700;
  text-decoration: none;
}
.table-link:hover {
  text-decoration: underline;
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
  .topbar { flex-wrap: wrap; }
}
</style>
"""

APP_SCRIPT = """
<script>
function showCopyFeedback(el, success) {
  el.style.borderColor = success ? '#1f58c3' : '#d1495b';
  setTimeout(function() { el.style.borderColor = ''; }, 600);
}
function legacyCopy(el) {
  el.focus();
  el.select();
  el.setSelectionRange(0, el.value.length);
  var ok = document.execCommand('copy');
  showCopyFeedback(el, ok);
}
function copyFromTextarea(id) {
  var el = document.getElementById(id);
  if (!el) return;
  var text = el.value;
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(
      function() { showCopyFeedback(el, true); },
      function() { legacyCopy(el); }
    );
    return;
  }
  legacyCopy(el);
}
function scrollToResult(id) {
  var el = document.getElementById(id);
  if (!el) return;
  window.requestAnimationFrame(function() {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('form').forEach(function(form) {
    form.addEventListener('submit', function() {
      var btn = form.querySelector('button[type="submit"]');
      if (btn && !btn.disabled) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = 'Processing\u2026';
      }
    });
  });
});
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
    <meta name="description" content="Automated EDQM and USP document retrieval — COA, MSDS, COO downloads and catalogue lookup.">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>V</text></svg>">
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


def _prune_download_cache() -> None:
    now = time.time()
    expired = [
        token
        for token, payload in _DOWNLOAD_CACHE.items()
        if now - float(payload.get("created_at", 0)) > DOWNLOAD_CACHE_TTL_SECONDS
    ]
    for token in expired:
        _DOWNLOAD_CACHE.pop(token, None)


def _store_download_payload(filename: str, data: bytes) -> str:
    _prune_download_cache()
    # Evict oldest entries if at capacity
    while len(_DOWNLOAD_CACHE) >= DOWNLOAD_CACHE_MAX_ENTRIES:
        oldest = min(_DOWNLOAD_CACHE, key=lambda k: float(_DOWNLOAD_CACHE[k].get("created_at", 0)))
        _DOWNLOAD_CACHE.pop(oldest, None)
    token = uuid4().hex
    _DOWNLOAD_CACHE[token] = {
        "filename": filename,
        "data": data,
        "created_at": time.time(),
    }
    return token


def _get_download_payload(token: str) -> tuple[str, bytes] | None:
    _prune_download_cache()
    payload = _DOWNLOAD_CACHE.get(token)
    if not payload:
        return None
    return str(payload["filename"]), bytes(payload["data"])


def _safe_href(url: str) -> str:
    """Validate and escape a URL for use in href attributes (prevent javascript: XSS)."""
    escaped = html.escape(url or "")
    if escaped and not escaped.startswith(("https://", "http://")):
        return ""
    return escaped


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
    from src.services.lookup import clean_lookup_fragment
    return clean_lookup_fragment(value)


def _lookup_query_candidates(raw_query: str) -> list[str]:
    return _svc_lookup_query_candidates(raw_query)


def _search_lookup_candidates(downloader, raw_query: str, limit: int = 8) -> tuple[list, str]:
    return _svc_search_lookup_candidates(downloader, raw_query, limit)


def _compact_lookup_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _lookup_match_type(raw_query: str, used_candidate: str) -> str:
    cleaned_query = _clean_lookup_fragment(raw_query)
    compact_raw = _compact_lookup_value(raw_query)
    compact_clean = _compact_lookup_value(cleaned_query)
    compact_used = _compact_lookup_value(used_candidate)

    if compact_used and compact_used == compact_raw:
        return "Exact"
    if compact_used and compact_used == compact_clean:
        return "Normalized"
    if compact_clean and compact_used and compact_clean.startswith(compact_used) and compact_clean != compact_used:
        return "Prefix fallback"
    if compact_clean and compact_used and compact_used in compact_clean:
        return "Broad match"
    return "Broad match"


def _edqm_lookup_enrichment(downloader, product_code: str) -> dict[str, str]:
    if not downloader.search_product(product_code):
        return {}

    summary = _edqm_detail_summary(downloader)
    return {
        "availability": summary.get("availability", ""),
        "price": summary.get("price", ""),
        "current_batch": summary.get("current_batch", ""),
        "unit_quantity": summary.get("unit_quantity", ""),
        "cas": summary.get("cas", ""),
    }


def _edqm_batch_summary(downloader, product_code: str) -> dict[str, str]:
    if not downloader.search_product(product_code):
        return {}

    current = getattr(downloader, "_current", None)
    extractor = getattr(downloader, "_extract_detail_fields", None)
    if not current or not callable(extractor):
        return {}

    try:
        fields = extractor(current.detail_html)
    except Exception:
        return {}

    return {
        "name": fields.get("Name") or current.name or product_code,
        "current_batch": fields.get("Current batch number", ""),
        "availability": fields.get("Availability", ""),
        "price": fields.get("Price", ""),
        "storage": fields.get("EDQM long term storage conditions", ""),
        "dispatching": fields.get("Dispatching conditions", ""),
        "unit_quantity": fields.get("Unit quantity per vial", ""),
        "sales_restriction": fields.get("Sales restriction", ""),
        "cas": _resolve_cas_number("edqm", downloader, product_code, fields.get("Name") or current.name or product_code),
        "detail_url": getattr(downloader, "get_detail_url", lambda _code: "")(product_code),
    }


def _usp_batch_summary(downloader, product_code: str) -> dict[str, str]:
    if not downloader.search_product(product_code):
        return {}

    product = getattr(downloader, "_current_product", None)
    if not product:
        return {}

    current_lot = None
    for lot in product.lots:
        if getattr(lot, "current", False):
            current_lot = lot
            break

    dated_lot = None
    for lot in product.lots:
        if getattr(lot, "valid_use_date", ""):
            dated_lot = lot
            break

    lot_for_display = current_lot or dated_lot or (product.lots[0] if product.lots else None)
    cas_number = _resolve_cas_number("usp", downloader, product_code, product.display_name or product.repository_id)
    return {
        "name": product.display_name or product.repository_id,
        "current_lot": getattr(lot_for_display, "lot_number", "") if lot_for_display else "",
        "valid_use_date": getattr(lot_for_display, "valid_use_date", "") if lot_for_display else "",
        "country_of_origin": getattr(lot_for_display, "origin_country", "") if lot_for_display else product.country_of_origin,
        "material_origin": getattr(lot_for_display, "material_origin", "") if lot_for_display else "",
        "certificate_valid": "Yes" if getattr(lot_for_display, "certificate_valid", False) else "No" if lot_for_display else "",
        "current_flag": "Yes" if getattr(lot_for_display, "current", False) else "No" if lot_for_display else "",
        "cas": cas_number,
        "detail_url": getattr(downloader, "get_detail_url", lambda _code: "")(product_code),
    }


def _batch_actionability(source: str, summary: dict[str, str]) -> tuple[str, str]:
    if source.lower() == "edqm":
        if summary.get("current_batch"):
            return "Current", "ok"
        return "Batch not found", "fail"

    current_lot = (summary.get("current_lot") or "").strip()
    certificate_valid = (summary.get("certificate_valid") or "").strip().lower() == "yes"
    current_flag = (summary.get("current_flag") or "").strip().lower() == "yes"
    valid_use_date = (summary.get("valid_use_date") or "").strip()

    if current_lot and current_flag and certificate_valid:
        return "Current / certificate valid", "ok"
    if current_lot and current_flag:
        return "Current", "ok"
    if current_lot and valid_use_date:
        return "Expired / dated lot only", "warn"
    if certificate_valid:
        return "Certificate valid", "warn"
    return "Batch not found", "fail"


def _bundle_name(source: str, code: str, position_name: str) -> str:
    return _svc_bundle_name(source, code, position_name)


def _zip_member_name(bundle: str, doc_type: str, file_path: Path) -> str:
    return _svc_zip_member_name(bundle, doc_type, file_path)


def _build_position_zip(bundle: str, files_by_doc: dict[str, Path]) -> bytes:
    return _svc_build_position_zip(bundle, files_by_doc)


def _build_batch_zip(
    source: str,
    successful_files: dict[str, dict[str, Path]],
    position_names: dict[str, str],
    manifest_text: str,
) -> bytes:
    return _svc_build_batch_zip(source, successful_files, position_names, manifest_text)


def _resolve_position_name(downloader, code: str) -> str:
    return _svc_resolve_position_name(downloader, code)


def _resolve_cas_number(source: str, downloader, code: str, position_name: str = "") -> str:
    return _svc_resolve_cas_number(source, downloader, code, position_name)


def _position_name_with_cas(position_name: str, cas_number: str) -> str:
    return _svc_append_cas_to_position_name(position_name, cas_number)


def _doc_status(result) -> str:
    return "OK" if getattr(result, "success", False) else "Fail"


def _edqm_detail_summary(downloader) -> dict[str, str]:
    current = getattr(downloader, "_current", None)
    extractor = getattr(downloader, "_extract_detail_fields", None)
    if not current or not callable(extractor):
        return {}
    try:
        fields = extractor(current.detail_html)
    except Exception:
        return {}
    return {
        "name": fields.get("Name") or current.name or current.code,
        "current_batch": fields.get("Current batch number", ""),
        "price": fields.get("Price", ""),
        "availability": fields.get("Availability", ""),
        "storage": fields.get("EDQM long term storage conditions", ""),
        "unit_quantity": fields.get("Unit quantity per vial", ""),
        "cas": _resolve_cas_number("edqm", downloader, current.code, fields.get("Name") or current.name or current.code),
    }


def _usp_search_summary(downloader, code: str) -> dict[str, str]:
    try:
        from src.downloaders.usp import REQUEST_TIMEOUT, USP_SEARCH_API
    except Exception:
        return {}

    require_session = getattr(downloader, "_require_session", None)
    compact = getattr(downloader, "_compact", None)
    if not callable(require_session) or not callable(compact):
        return {}

    try:
        session = require_session()
        resp = session.get(USP_SEARCH_API, params={"Ntt": code}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {}

    requested = compact(code)
    records = payload.get("resultsList", {}).get("records", [])
    for group in records:
        for rec in group.get("records") or []:
            attrs = rec.get("attributes", {})
            candidate = ((attrs.get("product.repositoryId") or attrs.get("product.id") or [""])[0] or "").strip()
            if candidate and compact(candidate) != requested:
                continue
            return {
                "price": ((attrs.get("product.listPrice") or [""])[0] or "").strip(),
                "in_stock": ((attrs.get("USPProductType.usp_in_stock") or [""])[0] or "").strip(),
                "orderable": ((attrs.get("USPProductType.usp_is_orderable") or [""])[0] or "").strip(),
                "ready_to_ship": ((attrs.get("USPProductType.usp_ready_to_ship") or [""])[0] or "").strip(),
                "packing_size": ((attrs.get("USPProductType.usp_packing_size") or [""])[0] or "").strip(),
                "uom": ((attrs.get("USPProductType.usp_uom") or [""])[0] or "").strip(),
                "cas": ((attrs.get("USPProductType.usp_cas_number") or [""])[0] or "").strip(),
                "molecular_formula": ((attrs.get("USPProductType.usp_molecular_formula") or [""])[0] or "").strip(),
                "current_lot": ((attrs.get("USPProductType.usp_current_lot_number") or [""])[0] or "").strip(),
                "category_type": ((attrs.get("USPProductType.usp_product_category_type") or [""])[0] or "").strip(),
            }
    return {}


def _format_lot_history(lots: list) -> str:
    parts: list[str] = []
    for lot in lots:
        lot_number = getattr(lot, "lot_number", "")
        if not lot_number:
            continue
        labels = []
        if getattr(lot, "current", False):
            labels.append("current")
        valid_use_date = getattr(lot, "valid_use_date", "")
        if valid_use_date:
            labels.append(valid_use_date)
        parts.append(f"{lot_number} ({', '.join(labels)})" if labels else lot_number)
    return "; ".join(parts)


def _usp_product_summary(downloader) -> dict[str, str]:
    product = getattr(downloader, "_current_product", None)
    if not product:
        return {}

    current_lot = ""
    current_country = ""
    current_material_origin = ""
    for lot in product.lots:
        if getattr(lot, "current", False):
            current_lot = getattr(lot, "lot_number", "")
            current_country = getattr(lot, "origin_country", "")
            current_material_origin = getattr(lot, "material_origin", "")
            break

    if not current_country and product.lots:
        current_country = getattr(product.lots[0], "origin_country", "")
    if not current_material_origin and product.lots:
        current_material_origin = getattr(product.lots[0], "material_origin", "")

    search_summary = _usp_search_summary(downloader, product.repository_id)

    return {
        "name": product.display_name or product.repository_id,
        "country_of_origin": current_country or product.country_of_origin,
        "current_lot": current_lot or search_summary.get("current_lot", ""),
        "lot_history": _format_lot_history(product.lots),
        "material_origin": current_material_origin,
        "category_type": search_summary.get("category_type", product.category_type),
        "sds_availability": "Yes" if product.display_sds_link else "No",
        "price": search_summary.get("price", ""),
        "in_stock": search_summary.get("in_stock", ""),
        "orderable": search_summary.get("orderable", ""),
        "packing_size": search_summary.get("packing_size", ""),
        "uom": search_summary.get("uom", ""),
        "cas": search_summary.get("cas", "") or _resolve_cas_number("usp", downloader, product.repository_id, product.display_name or product.repository_id),
        "molecular_formula": search_summary.get("molecular_formula", ""),
    }


def _download_batch(source: str, codes: list[str], doc_types: list[str]) -> dict[str, object]:
    if source == "edqm":
        from src.downloaders.edqm import EDQMDownloader as DownloaderCls
    else:
        from src.downloaders.usp import USPDownloader as DownloaderCls

    successful_files: dict[str, dict[str, Path]] = {}
    position_names: dict[str, str] = {}
    manifest_lines: list[str] = [
        f"Batch generated: {datetime.now(timezone.utc).isoformat()}",
        f"Source: {source.upper()}",
        f"Requested document types: {', '.join(doc_types)}",
        "",
    ]
    rows: list[dict[str, object]] = []

    with TemporaryDirectory() as tmpdir:
        downloader = DownloaderCls(download_dir=Path(tmpdir))
        downloader.start()
        try:
            for code in codes:
                manifest_lines.append(f"[{code}]")
                row: dict[str, object] = {
                    "code": code,
                    "source": source.upper(),
                    "name": "",
                    "summary": {},
                    "doc_results": {},
                    "notes": [],
                    "timeline": [],
                }
                row["timeline"] = [{"label": "Search", "status": "fail"}]
                if downloader.search_product(code):
                    summary = _edqm_detail_summary(downloader) if source == "edqm" else _usp_product_summary(downloader)
                    position_name = _resolve_position_name(downloader, code)
                    if summary.get("name"):
                        position_name = str(summary["name"])
                    cas_number = _resolve_cas_number(source, downloader, code, position_name)
                    if cas_number and not summary.get("cas"):
                        summary = dict(summary)
                        summary["cas"] = cas_number
                    row["name"] = position_name
                    row["summary"] = summary
                    position_names[code] = _position_name_with_cas(position_name, cas_number)
                    timeline = [
                        {"label": "Search", "status": "ok"},
                        {"label": "Metadata", "status": "ok"},
                    ]
                    doc_results: dict[str, dict[str, str]] = {}
                    files_downloaded = 0
                    notes: list[str] = []
                    for doc in doc_types:
                        result = downloader.download_document(code, doc)
                        status = _doc_status(result)
                        doc_entry = {
                            "status": status,
                            "file_name": Path(result.file_path).name if result.success and result.file_path else "",
                            "error": result.error or "",
                        }
                        doc_results[doc] = doc_entry
                        timeline.append({"label": doc, "status": "ok" if result.success else "fail"})
                        if result.success:
                            file_path = Path(result.file_path)
                            successful_files.setdefault(code, {})[doc] = file_path
                            manifest_lines.append(f"  {doc}: OK -> {file_path.name}")
                            files_downloaded += 1
                            if doc == "MSDS" and "sigma" in file_path.name.lower():
                                notes.append("Sigma fallback used for MSDS.")
                        else:
                            manifest_lines.append(f"  {doc}: FAIL -> {result.error}")
                            notes.append(f"{doc}: {result.error or 'Download failed'}")
                    timeline.append({"label": "Package", "status": "ok" if files_downloaded else "fail"})
                    row["doc_results"] = doc_results
                    row["timeline"] = timeline
                    row["notes"] = notes or (["All requested documents downloaded."] if files_downloaded == len(doc_types) else [])
                else:
                    row["notes"] = ["Product not found. Manual check required."]
                    row["doc_results"] = {
                        doc: {"status": "Fail", "file_name": "", "error": "Product not found"}
                        for doc in doc_types
                    }
                    row["timeline"] = [{"label": "Search", "status": "fail"}] + [
                        {"label": doc, "status": "fail"} for doc in doc_types
                    ]
                    for doc in doc_types:
                        manifest_lines.append(f"  {doc}: FAIL -> Product not found")
                manifest_lines.append("")
                rows.append(row)
        finally:
            downloader.stop()

        manifest_text = "\n".join(manifest_lines)
        batch_zip = _build_batch_zip(source, successful_files, position_names, manifest_text) if successful_files else b""
        return {
            "zip_bytes": batch_zip,
            "manifest_text": manifest_text,
            "position_count": len(successful_files),
            "rows": rows,
            "position_names": position_names,
        }


def _lookup_catalogue_numbers(source: str, names: list[str], limit: int = 8) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source = source.lower()

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        if source in {"edqm", "both"}:
            from src.downloaders.edqm import EDQMDownloader

            with EDQMDownloader(download_dir=tmp_path) as downloader:
                for query in names:
                    matches, used_candidate = _search_lookup_candidates(downloader, query, limit=limit)
                    if matches:
                        for idx, match in enumerate(matches, start=1):
                            enrichment = _edqm_lookup_enrichment(downloader, match.product_code) if idx <= 2 else {}
                            rows.append(
                                {
                                    "query": query,
                                    "matched_on": used_candidate,
                                    "match_type": _lookup_match_type(query, used_candidate),
                                    "rank": str(idx),
                                    "source": "EDQM",
                                    "code": match.product_code,
                                    "name": match.name,
                                    "cas": enrichment.get("cas", ""),
                                    "enrichment": enrichment,
                                }
                            )
                    else:
                        rows.append(
                            {
                                "query": query,
                                "matched_on": used_candidate,
                                "match_type": "No match",
                                "rank": "",
                                "source": "EDQM",
                                "code": "",
                                "name": "No match found",
                                "cas": "",
                                "enrichment": {},
                            }
                        )

        if source in {"usp", "both"}:
            from src.downloaders.usp import USPDownloader

            with USPDownloader(download_dir=tmp_path) as downloader:
                for query in names:
                    matches, used_candidate = _search_lookup_candidates(downloader, query, limit=limit)
                    if matches:
                        for idx, match in enumerate(matches, start=1):
                            rows.append(
                                {
                                    "query": query,
                                    "matched_on": used_candidate,
                                    "match_type": _lookup_match_type(query, used_candidate),
                                    "rank": str(idx),
                                    "source": "USP",
                                    "code": match.product_code,
                                    "name": match.name,
                                    "cas": str((getattr(match, "metadata", {}) or {}).get("cas", "")),
                                    "enrichment": dict(getattr(match, "metadata", {}) or {}),
                                }
                            )
                    else:
                        rows.append(
                            {
                                "query": query,
                                "matched_on": used_candidate,
                                "match_type": "No match",
                                "rank": "",
                                "source": "USP",
                                "code": "",
                                "name": "No match found",
                                "cas": "",
                                "enrichment": {},
                            }
                        )

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
                            "summary": {},
                            "detail_url": "",
                            "actionability": "Batch not found",
                            "actionability_class": "fail",
                        }
                    )
                    continue

                if source == "edqm":
                    summary = _edqm_batch_summary(downloader, code)
                    batch_number = summary.get("current_batch", "")
                else:
                    summary = _usp_batch_summary(downloader, code)
                    batch_number = summary.get("current_lot", "")

                position_name = summary.get("name") or _resolve_position_name(downloader, code)
                actionability, actionability_class = _batch_actionability(source, summary)

                rows.append(
                    {
                        "query": code,
                        "source": source.upper(),
                        "code": code,
                        "name": position_name,
                        "batch_number": batch_number,
                        "status": "OK" if batch_number else "Batch not found",
                        "summary": summary,
                        "detail_url": summary.get("detail_url", ""),
                        "actionability": actionability,
                        "actionability_class": actionability_class,
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
    results_html: str = "",
) -> str:
    source = source.lower()
    active_docs = {doc.upper() for doc in (selected_docs or ["COA", "MSDS", "COO"])}
    checked = lambda doc: "checked" if doc.upper() in active_docs else ""
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="surface">
  <form method="post" action="/download" class="panel section-stack">
      <div>
        <h2>Download Documents</h2>
        <p class="muted">Paste catalogue codes, choose documents, then review the summary below.</p>
      </div>
      {note}
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
      <div class="microcopy">One batch ZIP, folders by position plus CAS when available, summary table below, manifest kept as-is.</div>
  </form>
  {results_html}
</section>
"""


def _render_download_summary_table(source: str, rows: list[dict[str, object]], doc_types: list[str]) -> str:
    if source == "usp":
        headers = [
            "Code", "Product Name", "Country of Origin", "Current Lot", "Lot History",
            "Material Origin", "Category Type", "SDS Availability", "Price", "In Stock",
            "Orderable", "Packing Size", "UOM", "CAS", "Molecular Formula",
        ]
        accessors = [
            ("code", False),
            ("name", False),
            ("country_of_origin", False),
            ("current_lot", False),
            ("lot_history", True),
            ("material_origin", False),
            ("category_type", False),
            ("sds_availability", False),
            ("price", False),
            ("in_stock", False),
            ("orderable", False),
            ("packing_size", False),
            ("uom", False),
            ("cas", False),
            ("molecular_formula", False),
        ]
    else:
        headers = ["Code", "Product Name", "CAS", "Current Batch", "Price", "Availability", "Storage"]
        accessors = [
            ("code", False),
            ("name", False),
            ("cas", False),
            ("current_batch", False),
            ("price", False),
            ("availability", False),
            ("storage", False),
        ]

    headers += doc_types + ["Notes"]
    body: list[str] = []
    for row in rows:
        summary = row.get("summary", {}) if isinstance(row.get("summary", {}), dict) else {}
        doc_results = row.get("doc_results", {}) if isinstance(row.get("doc_results", {}), dict) else {}
        notes = " | ".join(str(note) for note in row.get("notes", []))
        cells: list[str] = []
        for key, wrap in accessors:
            value = row.get(key) if key in {"code", "name"} else summary.get(key, "")
            css = "wrap-cell" if wrap else ""
            cells.append(f'<td class="{css}">{_safe_text(str(value or "—"))}</td>')
        for doc in doc_types:
            doc_info = doc_results.get(doc, {}) if isinstance(doc_results.get(doc, {}), dict) else {}
            status = str(doc_info.get("status", "—"))
            css = "ok" if status == "OK" else "fail"
            cells.append(f'<td class="doc-status {css}">{_safe_text(status)}</td>')
        cells.append(f'<td class="wrap-cell">{_safe_text(notes or "—")}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    header_html = "".join(f"<th>{_safe_text(label)}</th>" for label in headers)
    return (
        '<section class="table-panel">'
        '<div class="table-header"><div><h3>Download Summary</h3><p class="muted">Metadata parsed from the source page plus document outcomes for each code.</p></div></div>'
        f'<div class="table-wrap"><table><thead><tr>{header_html}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        '</section>'
    )


def _render_download_results(
    source: str,
    codes: list[str],
    rows: list[dict[str, object]],
    doc_types: list[str],
    manifest_text: str,
    download_token: str = "",
    position_count: int = 0,
) -> str:
    download_url = f"/download-file?token={_safe_text(download_token)}" if download_token else ""
    if position_count and download_url:
        action_html = (
            f'<a class="button" href="{download_url}" download>Download Batch ZIP</a>'
        )
        auto_download_script = (
            f'<script>window.addEventListener("load",function(){{window.location.assign("{download_url}")}});</script>'
        )
    else:
        action_html = '<span class="button secondary" aria-disabled="true">No ZIP Available</span>'
        auto_download_script = ""
    return (
        '<div id="download-results-anchor"></div>'
        '<script>scrollToResult("download-results-anchor");</script>'
        + auto_download_script
        + '<section class="table-panel">'
        '<div class="result-actions">'
        '<div><h3>Download Result</h3><p class="muted">One ZIP at the top level. Each position is a folder inside the archive.</p></div>'
        f'<div style="display:flex; gap:10px; flex-wrap:wrap;">{action_html}<span class="status-pill">{position_count} positions packaged</span></div>'
        '</div>'
        '<div class="microcopy">Your ZIP should download automatically. If not, click the button above. Link expires after 15 minutes.</div>'
        + '</section>'
        + _render_download_summary_table(source, rows, doc_types)
        + f'<section class="manifest-panel"><h3>Batch Manifest</h3><pre>{_safe_text(manifest_text)}</pre></section>'
    )


def _lookup_form(source: str = "both", names: str = "", table_html: str = "", message: str = "") -> str:
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="surface">
    <form method="post" action="/lookup" class="panel section-stack">
      <div>
        <h2>Find Catalogue Numbers</h2>
        <p class="muted">Paste product names line by line and review matches directly below.</p>
      </div>
      {note}
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
  {table_html}
</section>
"""


def _batch_lookup_form(source: str = "edqm", codes: str = "", table_html: str = "", message: str = "") -> str:
    source = source.lower().strip()
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="surface">
    <form method="post" action="/batches" class="panel section-stack">
      <div>
        <h2>Current Batch Numbers</h2>
        <p class="muted">Paste catalogue codes line by line and review current batch values below.</p>
      </div>
      {note}
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
    tsv_rows = ["Query\tMatched On\tMatch Type\tSource\tCatalogue Number\tProduct Name\tCAS"]

    def render_lookup_details(row: dict[str, str]) -> str:
        enrichment = row.get("enrichment", {})
        if not isinstance(enrichment, dict):
            enrichment = {}

        if row["source"] == "USP":
            fields = [
                ("List Price", enrichment.get("price", "")),
                ("Current Lot", enrichment.get("current_lot", "")),
                ("In Stock", enrichment.get("in_stock", "")),
                ("Ready to Ship", enrichment.get("ready_to_ship", "")),
                ("Pack Size", enrichment.get("packing_size", "")),
                ("UOM", enrichment.get("uom", "")),
                ("CAS", enrichment.get("cas", "")),
                ("Molecular Formula", enrichment.get("molecular_formula", "")),
                ("Category", enrichment.get("category_type", "")),
            ]
        else:
            fields = [
                ("Availability", enrichment.get("availability", "")),
                ("Price", enrichment.get("price", "")),
                ("Current Batch", enrichment.get("current_batch", "")),
                ("Unit Quantity", enrichment.get("unit_quantity", "")),
                ("CAS", enrichment.get("cas", "")),
            ]

        visible = [(label, value) for label, value in fields if value]
        if not visible:
            return "—"

        body = "".join(
            f'<div class="lookup-detail-item"><b>{_safe_text(label)}</b><span>{_safe_text(str(value))}</span></div>'
            for label, value in visible
        )
        return (
            '<details class="lookup-details">'
            '<summary>View details</summary>'
            f'<div class="lookup-detail-grid">{body}</div>'
            '</details>'
        )

    for row in rows:
        tsv_rows.append(
            "\t".join(
                [
                    row["query"],
                    row.get("matched_on", ""),
                    row.get("match_type", ""),
                    row["source"],
                    row["code"],
                    row["name"],
                    row.get("cas", "") or ((row.get("enrichment", {}) or {}).get("cas", "") if isinstance(row.get("enrichment", {}), dict) else ""),
                ]
            )
        )
    tsv_text = "\n".join(tsv_rows)
    body = []
    for row in rows:
        status = row["code"] if row["code"] else "No match"
        klass = "status-ok" if row["code"] else "status-fail"
        cas_value = row.get("cas", "") or ((row.get("enrichment", {}) or {}).get("cas", "") if isinstance(row.get("enrichment", {}), dict) else "")
        body.append(
            "<tr>"
            f"<td>{_safe_text(row['query'])}</td>"
            f"<td>{_safe_text(row.get('matched_on', ''))}</td>"
            f"<td>{_safe_text(row.get('match_type', ''))}</td>"
            f"<td>{_safe_text(row['source'])}</td>"
            f'<td class="{klass} table-code">{_safe_text(status)}</td>'
            f"<td>{_safe_text(row['name'])}</td>"
            f'<td class="table-code">{_safe_text(cas_value or "—")}</td>'
            f"<td>{render_lookup_details(row)}</td>"
            "</tr>"
        )
    return (
        '<div id="lookup-results-anchor"></div>'
        '<script>scrollToResult("lookup-results-anchor");</script>'
        '<section class="table-panel">'
        '<div class="table-header">'
        '<div><h3>Lookup Results</h3><p class="muted">Choose the right position faster with matched-on context and lightweight source metadata.</p></div>'
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
        "<th>Original Input</th><th>Matched On</th><th>Match Type</th><th>Source</th><th>Catalogue Number</th><th>Product Name</th><th>CAS</th><th>Details</th>"
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
    source_key = (rows[0]["source"].lower() if rows else "edqm")
    if source_key == "usp":
        tsv_rows = ["Input\tSource\tCode\tName\tCAS\tCurrent Lot\tValid Use Date\tCOO\tMaterial Origin\tCertificate Valid\tActionability\tDetail URL"]
        header_html = (
            "<th>Input</th><th>Source</th><th>Code</th><th>Name</th><th>CAS</th><th>Current Lot</th><th>Valid Use Date</th>"
            "<th>COO</th><th>Material Origin</th><th>Certificate Valid</th><th>Actionability</th><th>Detail</th>"
        )
    else:
        tsv_rows = ["Input\tSource\tCode\tName\tCAS\tCurrent Batch\tAvailability\tPrice\tStorage\tDispatching\tActionability\tDetail URL"]
        header_html = (
            "<th>Input</th><th>Source</th><th>Code</th><th>Name</th><th>CAS</th><th>Current Batch</th><th>Availability</th>"
            "<th>Price</th><th>Storage</th><th>Dispatching</th><th>Actionability</th><th>Detail</th>"
        )
    body = []

    for row in rows:
        summary = row.get("summary", {}) if isinstance(row.get("summary", {}), dict) else {}
        detail_url = str(row.get("detail_url", "") or "")
        safe_url = _safe_href(detail_url)
        detail_link = f'<a class="table-link" href="{safe_url}" target="_blank" rel="noreferrer">Open</a>' if safe_url else "—"
        actionability = str(row.get("actionability", "") or row.get("status", ""))
        action_class = str(row.get("actionability_class", "fail"))

        if source_key == "usp":
            current_lot = summary.get("current_lot", "") or row["status"]
            valid_use_date = summary.get("valid_use_date", "")
            coo = summary.get("country_of_origin", "")
            material_origin = summary.get("material_origin", "")
            certificate_valid = summary.get("certificate_valid", "")
            cas_number = summary.get("cas", "")
            tsv_rows.append(
                "\t".join(
                    [
                        row["query"],
                        row["source"],
                        row["code"],
                        row["name"],
                        cas_number,
                        current_lot,
                        valid_use_date,
                        coo,
                        material_origin,
                        certificate_valid,
                        actionability,
                        detail_url,
                    ]
                )
            )
            body.append(
                "<tr>"
                f"<td>{_safe_text(row['query'])}</td>"
                f"<td>{_safe_text(row['source'])}</td>"
                f'<td class="table-code">{_safe_text(row["code"])}</td>'
                f"<td>{_safe_text(row['name'])}</td>"
                f'<td class="table-code">{_safe_text(cas_number or "—")}</td>'
                f'<td class="table-code">{_safe_text(current_lot)}</td>'
                f"<td>{_safe_text(valid_use_date or '—')}</td>"
                f"<td>{_safe_text(coo or '—')}</td>"
                f"<td>{_safe_text(material_origin or '—')}</td>"
                f"<td>{_safe_text(certificate_valid or '—')}</td>"
                f'<td><span class="action-pill {action_class}">{_safe_text(actionability)}</span></td>'
                f"<td>{detail_link}</td>"
                "</tr>"
            )
        else:
            current_batch = summary.get("current_batch", "") or row["status"]
            availability = summary.get("availability", "")
            price = summary.get("price", "")
            storage = summary.get("storage", "")
            dispatching = summary.get("dispatching", "")
            cas_number = summary.get("cas", "")
            tsv_rows.append(
                "\t".join(
                    [
                        row["query"],
                        row["source"],
                        row["code"],
                        row["name"],
                        cas_number,
                        current_batch,
                        availability,
                        price,
                        storage,
                        dispatching,
                        actionability,
                        detail_url,
                    ]
                )
            )
            body.append(
                "<tr>"
                f"<td>{_safe_text(row['query'])}</td>"
                f"<td>{_safe_text(row['source'])}</td>"
                f'<td class="table-code">{_safe_text(row["code"])}</td>'
                f"<td>{_safe_text(row['name'])}</td>"
                f'<td class="table-code">{_safe_text(cas_number or "—")}</td>'
                f'<td class="table-code">{_safe_text(current_batch)}</td>'
                f"<td>{_safe_text(availability or '—')}</td>"
                f"<td>{_safe_text(price or '—')}</td>"
                f"<td>{_safe_text(storage or '—')}</td>"
                f"<td>{_safe_text(dispatching or '—')}</td>"
                f'<td><span class="action-pill {action_class}">{_safe_text(actionability)}</span></td>'
                f"<td>{detail_link}</td>"
                "</tr>"
            )

    tsv_text = "\n".join(tsv_rows)
    return (
        '<div id="batch-results-anchor"></div>'
        '<script>scrollToResult("batch-results-anchor");</script>'
        '<section class="table-panel">'
        '<div class="table-header">'
        '<div><h3>Current Batch Results</h3><p class="muted">Batch view enriched with source metadata, actionability, and direct detail links.</p></div>'
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
        + header_html
        + "</tr></thead><tbody>"
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
        <li>One batch ZIP with one folder per position.</li>
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

    if path.endswith("/download-file"):
        page = "download-file"
    elif path.endswith("/download"):
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
        if page == "download-file":
            token = request.query_params.get("token", "")
            return download_documents_file(token=token)
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
            _download_form(source="edqm", codes=codes, message="Select a valid source (EDQM or USP).", selected_docs=clean_doc_types),
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
        batch_result = _download_batch(source, clean_codes, clean_doc_types)
    except Exception as exc:
        body = _download_form(
            source=source,
            codes=codes,
            message=f"Download failed: {exc}",
            selected_docs=clean_doc_types,
        )
        return _page("Download Documents", body, active="download")

    manifest_text = str(batch_result.get("manifest_text", ""))
    position_count = int(batch_result.get("position_count", 0))
    rows = list(batch_result.get("rows", []))
    zip_bytes = bytes(batch_result.get("zip_bytes", b""))
    download_token = ""
    if zip_bytes:
        filename = f"{source.upper()}_BATCH_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{position_count}pos.zip"
        download_token = _store_download_payload(filename, zip_bytes)
    message = "Download complete. Your ZIP is downloading automatically." if position_count else "No files were downloaded. Review the summary and manifest below."

    results_html = _render_download_results(
        source=source,
        codes=clean_codes,
        rows=rows,
        doc_types=clean_doc_types,
        manifest_text=manifest_text,
        download_token=download_token,
        position_count=position_count,
    )
    return _page(
        "Download Documents",
        _download_form(
            source=source,
            codes=codes,
            message=message,
            selected_docs=clean_doc_types,
            results_html=results_html,
        ),
        active="download",
    )


@app.get("/download-file")
def download_documents_file(token: str = ""):
    if not token:
        return Response("Missing download token.", status_code=400, media_type="text/plain")

    cached = _get_download_payload(token)
    if not cached:
        return Response("Download expired or not found. Please re-submit the form.", status_code=404, media_type="text/plain")

    filename, data = cached
    return StreamingResponse(
        BytesIO(data),
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
            _batch_lookup_form(source="edqm", codes=codes, message="Select a valid source (EDQM or USP)."),
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
