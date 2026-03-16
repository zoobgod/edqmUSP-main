"""Vercel-compatible ASGI frontend for edqmUSP."""

from __future__ import annotations

import html
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

app = FastAPI(title="edqmUSP")

APP_CSS = """
<style>
:root {
  --paper: #f6f1e8;
  --ink: #1d1a16;
  --muted: #6a6257;
  --card: #fffaf2;
  --line: #d8cdbd;
  --green: #155e63;
  --green-2: #1d7a74;
  --red: #9b2c2c;
  --gold: #b9832f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background:
    radial-gradient(circle at top right, rgba(185,131,47,0.13), transparent 28%),
    linear-gradient(180deg, #fbf7f1, var(--paper));
  color: var(--ink);
  font-family: Georgia, "Times New Roman", serif;
}
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 18px 64px;
}
.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 26px;
}
.nav a {
  color: var(--ink);
  text-decoration: none;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(255,250,242,0.82);
}
.nav a.active {
  background: var(--green);
  color: #fff;
  border-color: var(--green);
}
.hero {
  padding: 28px;
  border: 1px solid var(--line);
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(255,250,242,0.95), rgba(241,233,219,0.9));
  box-shadow: 0 18px 40px rgba(60, 45, 20, 0.08);
}
.hero h1, .hero h2 {
  margin: 0 0 12px;
  line-height: 1.05;
}
.hero p, .note, .muted {
  color: var(--muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin-top: 18px;
}
.card {
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--card);
}
.button, button {
  display: inline-block;
  background: linear-gradient(135deg, var(--green), var(--green-2));
  color: #fff;
  border: 0;
  border-radius: 14px;
  padding: 12px 18px;
  font: inherit;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}
.button.secondary {
  background: linear-gradient(135deg, #7c5a1d, var(--gold));
}
form {
  margin-top: 18px;
}
label {
  display: block;
  font-weight: 700;
  margin: 14px 0 8px;
}
textarea, select, input[type="text"] {
  width: 100%;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: #fffefb;
  font: inherit;
}
textarea {
  min-height: 180px;
  resize: vertical;
}
.checks {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin: 10px 0 18px;
}
.checks label {
  margin: 0;
  font-weight: 400;
}
.table-wrap {
  overflow-x: auto;
  margin-top: 18px;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: #fffdf8;
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
}
th, td {
  padding: 12px 14px;
  border-bottom: 1px solid #ece3d7;
  text-align: left;
  vertical-align: top;
}
th {
  background: #efe5d6;
}
.status-ok {
  color: #1d5f35;
  font-weight: 700;
}
.status-fail {
  color: var(--red);
  font-weight: 700;
}
pre {
  white-space: pre-wrap;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #fffdf8;
  padding: 16px;
  overflow-x: auto;
}
@media (max-width: 700px) {
  .page { padding: 18px 12px 42px; }
  .hero, .card { padding: 18px; }
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
    {APP_CSS}
  </head>
  <body>
    <main class="page">
      <nav class="nav">{nav_html}</nav>
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

    if source in {"edqm", "both"}:
        from src.downloaders.edqm import EDQMDownloader

        with EDQMDownloader() as downloader:
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

        with USPDownloader() as downloader:
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


def _download_form(source: str = "edqm", codes: str = "", message: str = "") -> str:
    source = source.lower()
    checked = lambda doc: "checked" if doc in {"COA", "MSDS", "COO"} else ""
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="hero">
  <h1>Instant Document Download</h1>
  <p>Paste catalogue numbers, choose the source and documents, and the app will generate one downloadable batch ZIP instead of making you search each item manually.</p>
  {note}
  <form method="post" action="/download">
    <label for="source">Source</label>
    <select id="source" name="source">
      <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
      <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
    </select>

    <label for="codes">Catalogue numbers</label>
    <textarea id="codes" name="codes" placeholder="Y0001532&#10;G0400006">{_safe_text(codes)}</textarea>

    <label>Documents</label>
    <div class="checks">
      <label><input type="checkbox" name="doc_types" value="COA" checked> COA</label>
      <label><input type="checkbox" name="doc_types" value="MSDS" checked> MSDS</label>
      <label><input type="checkbox" name="doc_types" value="COO" checked> COO</label>
    </div>

    <button type="submit">Generate Batch ZIP</button>
  </form>
</section>
"""


def _lookup_form(source: str = "both", names: str = "", table_html: str = "", message: str = "") -> str:
    note = f'<p class="note">{_safe_text(message)}</p>' if message else ""
    return f"""
<section class="hero">
  <h1>Catalogue Finder</h1>
  <p>Paste product names in bulk and get catalogue numbers back without opening EDQM or USP catalogues manually. Use one line per product name and search EDQM, USP, or both at once.</p>
  {note}
  <form method="post" action="/lookup">
    <label for="source">Where should we search?</label>
    <select id="source" name="source">
      <option value="both" {"selected" if source == "both" else ""}>Both</option>
      <option value="edqm" {"selected" if source == "edqm" else ""}>EDQM</option>
      <option value="usp" {"selected" if source == "usp" else ""}>USP</option>
    </select>

    <label for="names">Product names, one per line</label>
    <textarea id="names" name="names" placeholder="PICOTAMIDE MONOHYDRATE CRS&#10;Cisplatin&#10;Glycerol Monostearate 40-55 CRS">{_safe_text(names)}</textarea>

    <button type="submit" class="button secondary">Find Matching Catalogue Numbers</button>
  </form>
  {table_html}
</section>
"""


def _lookup_results_table(rows: list[dict[str, str]]) -> str:
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
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Query</th><th>Source</th><th>Catalogue Number</th><th>Product Name</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


@app.get("/", response_class=HTMLResponse)
def landing_page() -> HTMLResponse:
    body = """
<section class="hero">
  <h1>edqmUSP</h1>
  <p>Stop hunting through catalogues one position at a time. This deployment gives you two focused tools on the same domain: instant document download by catalogue number, and bulk catalogue lookup by product name.</p>
  <div class="grid">
    <section class="card">
      <h2>Download Documents</h2>
      <p>Enter EDQM or USP catalogue numbers and generate a batch ZIP with COA, MSDS, and COO files.</p>
      <a class="button" href="/download">Open Downloader</a>
    </section>
    <section class="card">
      <h2>Find Catalogue Numbers</h2>
      <p>Paste product names in bulk and get matching EDQM and USP catalogue numbers without manual searching.</p>
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

    form = await request.form()
    if page == "download":
        source = str(form.get("source") or "edqm")
        codes = str(form.get("codes") or "")
        doc_types = [str(value) for value in form.getlist("doc_types")]
        return download_documents(source=source, codes=codes, doc_types=doc_types)

    if page == "lookup":
        source = str(form.get("source") or "both")
        names = str(form.get("names") or "")
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
        return _page("Download Documents", _download_form(source="edqm", codes=codes, message="Invalid source."), active="download")
    if not clean_codes:
        return _page("Download Documents", _download_form(source=source, codes=codes, message="Enter at least one catalogue number."), active="download")
    if not clean_doc_types:
        return _page("Download Documents", _download_form(source=source, codes=codes, message="Select at least one document type."), active="download")

    batch_zip, manifest_text, position_count = _download_batch(source, clean_codes, clean_doc_types)
    if not batch_zip:
        body = _download_form(source=source, codes=codes, message="No files were downloaded. See manifest below.") + f"<pre>{_safe_text(manifest_text)}</pre>"
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

    rows = _lookup_catalogue_numbers(source, clean_names)
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
