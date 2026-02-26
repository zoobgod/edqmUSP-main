"""Streamlit UI for edqmUSP - public document download + YDisk upload."""

import io
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src.config import DOWNLOAD_DIR, YDISK_TOKEN
from src.downloaders.edqm import EDQMDownloader
from src.downloaders.usp import USPDownloader
from src.uploaders.ydisk import YDiskUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

st.set_page_config(page_title="edqmUSP", page_icon="V", layout="wide")
st.title("edqmUSP - Document Downloader & Uploader")
st.caption(
    "Download COA, MSDS and COO from EDQM/USP public pages, then upload to Yandex Disk."
)


def _init_state():
    st.session_state.setdefault("download_batches", [])
    st.session_state.setdefault("download_batch_counter", 0)


_init_state()

with st.sidebar:
    st.info("EDQM and USP downloads use public URLs. Login credentials are not required.")
    with st.expander("Configuration", expanded=False):
        st.subheader("Yandex Disk")
        ydisk_token = st.text_input("YDisk Token", value=YDISK_TOKEN, type="password")
        if ydisk_token and st.button("Test YDisk Connection"):
            uploader = YDiskUploader(token=ydisk_token)
            if uploader.connect():
                st.success("Connected to Yandex Disk")
            else:
                st.error("Failed to connect. Check your token.")

        st.subheader("Settings")
        download_dir = st.text_input("Download directory", value=str(DOWNLOAD_DIR))


def _download_documents(source: str, codes: list[str], doc_types: list[str], base_dir: Path):
    progress = st.progress(0)
    status = st.empty()
    results_container = st.container()
    download_container = st.container()

    successful_files: dict[str, dict[str, Path]] = {}
    position_names: dict[str, str] = {}
    batch_started_at = datetime.now()
    batch_id = _next_batch_id()

    downloader_cls = EDQMDownloader if source == "edqm" else USPDownloader
    downloader = downloader_cls(download_dir=base_dir)
    downloader.start()

    try:
        total = max(1, len(codes) * len(doc_types))
        done = 0

        for code in codes:
            status.info(f"Searching for {code}...")
            if downloader.search_product(code):
                position_names[code] = _resolve_position_name(downloader, code)
                for doc in doc_types:
                    status.info(f"Downloading {doc} for {code}...")
                    result = downloader.download_document(code, doc)
                    done += 1
                    progress.progress(done / total)

                    with results_container:
                        if result.success:
                            st.success(f"{code} {doc}: {result.file_path}")
                            successful_files.setdefault(code, {})[doc] = Path(result.file_path)
                        else:
                            st.error(f"{code} {doc}: {result.error}")
                            if (
                                source == "edqm"
                                and doc == "MSDS"
                                and "Sigma SDS fallback failed" in result.error
                            ):
                                st.markdown(f"[Open Sigma SDS for {code}]({_sigma_sds_url(code)})")
            else:
                for doc in doc_types:
                    done += 1
                    progress.progress(done / total)
                    with results_container:
                        st.error(f"{code} {doc}: Product not found")

        status.success(f"{source.upper()} downloads complete!")

        if successful_files:
            _record_batch(batch_id, source, batch_started_at, successful_files, position_names)

            with download_container:
                st.markdown("### Download to your PC")
                batch_zip_data = _build_batch_zip(source, successful_files, position_names)
                st.download_button(
                    label="Download All (Nested ZIP)",
                    data=batch_zip_data,
                    file_name=f"{_safe_file_part(source.upper())}_BATCH_{batch_id}.zip",
                    mime="application/zip",
                    key=f"zip-batch-{source}-{batch_id}",
                )
                st.caption("Contains one ZIP per position bundle.")

                for code in codes:
                    files_by_doc = successful_files.get(code, {})
                    if not files_by_doc:
                        continue

                    position_name = position_names.get(code, code)
                    bundle_name = _bundle_name(source, code, position_name)
                    st.markdown(f"**{bundle_name}**")
                    st.caption(f"Catalogue: {code}")

                    cols = st.columns(5)
                    for idx, doc in enumerate(("COA", "MSDS", "COO")):
                        file_path = files_by_doc.get(doc)
                        if not file_path or not file_path.exists():
                            cols[idx].write(f"{doc}: -")
                            continue

                        data = file_path.read_bytes()
                        mime = _mime_type_for(file_path)
                        cols[idx].download_button(
                            label=doc,
                            data=data,
                            file_name=file_path.name,
                            mime=mime,
                            key=f"dl-{source}-{batch_id}-{code}-{doc}",
                        )

                    zip_data = _build_zip_for_position(bundle_name, files_by_doc)
                    cols[3].download_button(
                        label="Position ZIP",
                        data=zip_data,
                        file_name=f"{_safe_file_part(bundle_name)}.zip",
                        mime="application/zip",
                        key=f"zip-{source}-{batch_id}-{code}",
                    )
                    cols[4].write("")
    finally:
        downloader.stop()


def _resolve_position_name(downloader, code: str) -> str:
    getter = getattr(downloader, "get_position_name", None)
    if callable(getter):
        try:
            name = (getter(code) or "").strip()
            if name:
                return name
        except Exception as exc:  # pragma: no cover
            logging.warning("Could not resolve position name for %s: %s", code, exc)
    return code


def _safe_file_part(value: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]+', "_", (value or "").strip()).strip(".")
    return sanitized or "position"


def _mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _bundle_name(source: str, code: str, position_name: str) -> str:
    return f"{source.upper()}_{code}_{position_name}".strip()


def _zip_member_name(bundle_name: str, doc_type: str, file_path: Path) -> str:
    if doc_type == "COO":
        # Keep COO naming as country-derived source filename (pdf/txt).
        return file_path.name

    suffix = file_path.suffix.lower() or ".pdf"
    return f"{_safe_file_part(bundle_name)}_{doc_type}{suffix}"


def _build_zip_for_position(bundle_name: str, files_by_doc: dict[str, Path]) -> bytes:
    buffer = io.BytesIO()
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
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for code, files_by_doc in successful_files.items():
            position_name = position_names.get(code, code)
            bundle_name = _bundle_name(source, code, position_name)
            pos_zip = _build_zip_for_position(bundle_name, files_by_doc)
            archive.writestr(f"{_safe_file_part(bundle_name)}.zip", pos_zip)

    buffer.seek(0)
    return buffer.getvalue()


def _sigma_sds_url(code: str) -> str:
    safe_code = re.sub(r"[^a-z0-9]+", "", (code or "").lower())
    return f"https://www.sigmaaldrich.com/SE/en/sds/sial/{safe_code}?userType=anonymous"


def _next_batch_id() -> int:
    st.session_state["download_batch_counter"] += 1
    return int(st.session_state["download_batch_counter"])


def _record_batch(
    batch_id: int,
    source: str,
    started_at: datetime,
    successful_files: dict[str, dict[str, Path]],
    position_names: dict[str, str],
):
    positions = []
    for code, files_by_doc in successful_files.items():
        position_name = position_names.get(code, code)
        bundle_name = _bundle_name(source, code, position_name)
        file_entries = []

        for doc_type in ("COA", "MSDS", "COO"):
            path = files_by_doc.get(doc_type)
            if not path or not path.exists():
                continue

            stats = path.stat()
            file_entries.append(
                {
                    "doc_type": doc_type,
                    "file_name": path.name,
                    "file_path": str(path),
                    "size_kb": round(stats.st_size / 1024, 1),
                    "saved_at": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        if file_entries:
            positions.append(
                {
                    "code": code,
                    "position_name": position_name,
                    "bundle_name": bundle_name,
                    "files": file_entries,
                }
            )

    if not positions:
        return

    st.session_state["download_batches"].append(
        {
            "id": batch_id,
            "source": source.upper(),
            "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "positions": positions,
        }
    )


def _clear_download_cache(base_dir: Path):
    for source in ("edqm", "usp"):
        source_dir = base_dir / source
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

    st.session_state["download_batches"] = []
    st.session_state["download_batch_counter"] = 0


def _collect_download_file_rows(base_dir: Path) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for source in ("edqm", "usp"):
        source_dir = base_dir / source
        if not source_dir.exists():
            continue
        for file_path in sorted(source_dir.iterdir()):
            if not file_path.is_file():
                continue
            stats = file_path.stat()
            rows.append(
                {
                    "source": source.upper(),
                    "file_name": file_path.name,
                    "size_kb": round(stats.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "path": str(file_path),
                }
            )
    return rows


def _get_query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value or "")
    except Exception:
        try:
            params = st.experimental_get_query_params()
            values = params.get(name, [])
            return str(values[0]) if values else ""
        except Exception:
            return ""


def _flappy_game_html() -> str:
    return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body {
        margin: 0;
        padding: 0;
        background: #f4efe6;
        font-family: "Trebuchet MS", Verdana, sans-serif;
        color: #2d2a26;
      }
      .wrap {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        padding: 8px 0 0;
      }
      #game {
        width: 420px;
        height: 620px;
        max-width: 95vw;
        border: 2px solid #2d2a26;
        border-radius: 12px;
        box-shadow: 0 10px 24px rgba(0,0,0,0.18);
        background: #cde7f8;
      }
      .hint {
        font-size: 13px;
        opacity: 0.9;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <canvas id="game" width="420" height="620"></canvas>
      <div class="hint">Press Space / Arrow Up / Click to flap</div>
    </div>

    <script>
      const canvas = document.getElementById("game");
      const ctx = canvas.getContext("2d");
      const W = canvas.width;
      const H = canvas.height;

      const gravity = 0.43;
      const flapImpulse = -7.8;
      const pipeWidth = 72;
      const pipeGap = 165;
      const pipeSpeed = 2.8;
      const pipeSpawnEvery = 105;
      const groundHeight = 62;

      let bird = { x: 96, y: H * 0.42, vy: 0, r: 14 };
      let pipes = [];
      let frame = 0;
      let score = 0;
      let best = 0;
      let started = false;
      let gameOver = false;

      function reset() {
        bird = { x: 96, y: H * 0.42, vy: 0, r: 14 };
        pipes = [];
        frame = 0;
        score = 0;
        started = false;
        gameOver = false;
      }

      function flap() {
        if (!started) started = true;
        if (gameOver) {
          reset();
          started = true;
        }
        bird.vy = flapImpulse;
      }

      function addPipe() {
        const minTop = 70;
        const maxTop = H - groundHeight - pipeGap - 70;
        const top = minTop + Math.random() * (maxTop - minTop);
        pipes.push({ x: W + 8, top, passed: false });
      }

      function collidesPipe(p) {
        const bx = bird.x;
        const by = bird.y;
        const br = bird.r;
        const withinX = bx + br > p.x && bx - br < p.x + pipeWidth;
        const hitTop = by - br < p.top;
        const hitBottom = by + br > p.top + pipeGap;
        return withinX && (hitTop || hitBottom);
      }

      function update() {
        frame += 1;

        if (started && !gameOver) {
          bird.vy += gravity;
          bird.y += bird.vy;

          if (frame % pipeSpawnEvery === 0) addPipe();

          for (const p of pipes) {
            p.x -= pipeSpeed;
            if (!p.passed && p.x + pipeWidth < bird.x) {
              p.passed = true;
              score += 1;
              best = Math.max(best, score);
            }
            if (collidesPipe(p)) gameOver = true;
          }
          pipes = pipes.filter(p => p.x + pipeWidth > -4);

          if (bird.y - bird.r < 0) {
            bird.y = bird.r;
            bird.vy = 0;
          }
          if (bird.y + bird.r > H - groundHeight) {
            bird.y = H - groundHeight - bird.r;
            gameOver = true;
          }
        } else if (!started) {
          bird.y += Math.sin(frame / 12) * 0.35;
        }
      }

      function drawBackground() {
        const sky = ctx.createLinearGradient(0, 0, 0, H);
        sky.addColorStop(0, "#d7f0ff");
        sky.addColorStop(1, "#b9dfef");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, W, H);

        ctx.fillStyle = "#8db36f";
        ctx.fillRect(0, H - groundHeight, W, groundHeight);
        ctx.fillStyle = "#708e57";
        ctx.fillRect(0, H - groundHeight, W, 7);
      }

      function drawPipes() {
        for (const p of pipes) {
          ctx.fillStyle = "#3f8e4f";
          ctx.fillRect(p.x, 0, pipeWidth, p.top);
          ctx.fillRect(p.x, p.top + pipeGap, pipeWidth, H - (p.top + pipeGap) - groundHeight);

          ctx.fillStyle = "#336f3d";
          ctx.fillRect(p.x - 4, p.top - 16, pipeWidth + 8, 16);
          ctx.fillRect(p.x - 4, p.top + pipeGap, pipeWidth + 8, 16);
        }
      }

      function drawBird() {
        ctx.beginPath();
        ctx.fillStyle = "#f2c14e";
        ctx.arc(bird.x, bird.y, bird.r, 0, Math.PI * 2);
        ctx.fill();

        ctx.beginPath();
        ctx.fillStyle = "#2d2a26";
        ctx.arc(bird.x + 5, bird.y - 4, 2.5, 0, Math.PI * 2);
        ctx.fill();

        ctx.beginPath();
        ctx.fillStyle = "#e57423";
        ctx.moveTo(bird.x + 11, bird.y);
        ctx.lineTo(bird.x + 21, bird.y + 3);
        ctx.lineTo(bird.x + 11, bird.y + 7);
        ctx.closePath();
        ctx.fill();
      }

      function drawHud() {
        ctx.fillStyle = "#1f1c18";
        ctx.font = "bold 28px Trebuchet MS, Verdana, sans-serif";
        ctx.fillText(String(score), 16, 38);

        ctx.font = "bold 14px Trebuchet MS, Verdana, sans-serif";
        ctx.fillText("BEST " + String(best), 16, 58);

        if (!started) {
          ctx.fillStyle = "rgba(20,20,20,0.65)";
          ctx.fillRect(36, 238, W - 72, 92);
          ctx.fillStyle = "#fff";
          ctx.font = "bold 24px Trebuchet MS, Verdana, sans-serif";
          ctx.fillText("Flappy Mini", W / 2 - 72, 274);
          ctx.font = "14px Trebuchet MS, Verdana, sans-serif";
          ctx.fillText("Press Space / Click to start", W / 2 - 95, 303);
        }

        if (gameOver) {
          ctx.fillStyle = "rgba(20,20,20,0.72)";
          ctx.fillRect(46, 224, W - 92, 126);
          ctx.fillStyle = "#fff";
          ctx.font = "bold 28px Trebuchet MS, Verdana, sans-serif";
          ctx.fillText("Game Over", W / 2 - 78, 268);
          ctx.font = "15px Trebuchet MS, Verdana, sans-serif";
          ctx.fillText("Score " + String(score) + "  Best " + String(best), W / 2 - 76, 296);
          ctx.fillText("Press Space/Click to retry", W / 2 - 96, 320);
        }
      }

      function render() {
        drawBackground();
        drawPipes();
        drawBird();
        drawHud();
      }

      function loop() {
        update();
        render();
        requestAnimationFrame(loop);
      }

      document.addEventListener("keydown", (e) => {
        if (e.code === "Space" || e.code === "ArrowUp") {
          e.preventDefault();
          flap();
        }
      });
      canvas.addEventListener("mousedown", flap);
      canvas.addEventListener("touchstart", (e) => {
        e.preventDefault();
        flap();
      }, { passive: false });

      render();
      requestAnimationFrame(loop);
    </script>
  </body>
</html>
"""


def _render_hidden_flappy_game():
    game_open = _get_query_param("v_game") == "1"

    floating_btn = """
<style>
.v-flappy-pill {
  position: fixed;
  right: 18px;
  bottom: 16px;
  padding: 10px 14px;
  border-radius: 999px;
  color: #ffffff !important;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none !important;
  letter-spacing: 0.1px;
  box-shadow: 0 10px 24px rgba(0,0,0,0.22);
  z-index: 9999;
  transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
  opacity: 0.96;
}
.v-flappy-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(0,0,0,0.28);
  opacity: 1;
}
#v-flappy-open {
  background: linear-gradient(135deg, #0d9488, #0f766e);
}
#v-flappy-close {
  background: linear-gradient(135deg, #b91c1c, #991b1b);
}
@media (max-width: 700px) {
  .v-flappy-pill {
    right: 12px;
    bottom: 12px;
    padding: 9px 12px;
    font-size: 12px;
  }
}
</style>
"""
    if game_open:
        floating_btn += '<a id="v-flappy-close" class="v-flappy-pill" href="?v_game=0">Close Game</a>'
    else:
        floating_btn += '<a id="v-flappy-open" class="v-flappy-pill" href="?v_game=1">Play V-Bird</a>'

    st.markdown(floating_btn, unsafe_allow_html=True)

    if not game_open:
        return

    st.markdown("### Flappy Mini")
    st.caption("Press Space / Arrow Up / click to play.")
    components.html(_flappy_game_html(), height=680, scrolling=False)


# --- Main Area: Tabs ---
tab_edqm, tab_usp, tab_upload, tab_status = st.tabs(
    ["EDQM Download", "USP Download", "Upload to YDisk", "Downloaded Files"]
)

# --- EDQM Tab ---
with tab_edqm:
    st.subheader("Download from EDQM")
    edqm_codes = st.text_area(
        "Enter EDQM product codes (one per line)",
        placeholder="Y0001532\nY0001234",
        height=150,
    )
    edqm_doc_types = st.multiselect(
        "Document types", ["COA", "MSDS", "COO"], default=["COA", "MSDS", "COO"]
    )

    if st.button("Download from EDQM", type="primary"):
        codes = [c.strip() for c in edqm_codes.strip().splitlines() if c.strip()]
        if not codes:
            st.warning("Enter at least one product code.")
        else:
            _download_documents("edqm", codes, edqm_doc_types, Path(download_dir))

# --- USP Tab ---
with tab_usp:
    st.subheader("Download from USP")
    usp_codes = st.text_area(
        "Enter USP catalogue numbers (one per line)",
        placeholder="1134357\n1234567",
        height=150,
    )
    usp_doc_types = st.multiselect(
        "Document types",
        ["COA", "MSDS", "COO"],
        default=["COA", "MSDS", "COO"],
        key="usp_doc_types",
    )

    if st.button("Download from USP", type="primary"):
        codes = [c.strip() for c in usp_codes.strip().splitlines() if c.strip()]
        if not codes:
            st.warning("Enter at least one catalogue number.")
        else:
            _download_documents("usp", codes, usp_doc_types, Path(download_dir))

# --- Upload Tab ---
with tab_upload:
    st.subheader("Upload to Yandex Disk")

    if not ydisk_token:
        st.warning("Configure your YDisk token in the sidebar first.")
    else:
        upload_source = st.radio(
            "Upload source",
            ["EDQM downloads", "USP downloads", "All downloads"],
        )

        if st.button("Upload to Yandex Disk", type="primary"):
            uploader = YDiskUploader(token=ydisk_token)
            if not uploader.connect():
                st.error("Failed to connect to Yandex Disk. Check your token.")
            else:
                dl_path = Path(download_dir)
                dirs_to_upload = []

                if upload_source == "EDQM downloads":
                    dirs_to_upload = [("edqm", dl_path / "edqm")]
                elif upload_source == "USP downloads":
                    dirs_to_upload = [("usp", dl_path / "usp")]
                else:
                    dirs_to_upload = [("edqm", dl_path / "edqm"), ("usp", dl_path / "usp")]

                for subfolder, dir_path in dirs_to_upload:
                    if not dir_path.exists():
                        st.info(f"No {subfolder.upper()} downloads found.")
                        continue

                    files = [p for p in dir_path.iterdir() if p.is_file()]
                    if not files:
                        st.info(f"No files in {subfolder.upper()} download folder.")
                        continue

                    st.info(f"Uploading {len(files)} files from {subfolder.upper()}...")
                    results = uploader.upload_directory(dir_path, subfolder)

                    for fname, success in results.items():
                        if success:
                            st.success(f"Uploaded: {fname}")
                        else:
                            st.error(f"Failed: {fname}")

                st.success("Upload complete!")

# --- Status Tab ---
with tab_status:
    st.subheader("Downloaded Files")
    dl_path = Path(download_dir)

    action_col1, action_col2 = st.columns([1, 3])
    with action_col1:
        if st.button("Clear Download Cache", type="secondary"):
            _clear_download_cache(dl_path)
            st.success("Download cache cleared.")
    with action_col2:
        st.caption("Removes all files from downloads/edqm and downloads/usp and resets batch history.")

    st.markdown("### Download Batches")
    batches = st.session_state.get("download_batches", [])
    if not batches:
        st.info("No download batches recorded in this session yet.")
    else:
        for batch in reversed(batches):
            title = f"Batch #{batch['id']} - {batch['source']} - {batch['started_at']}"
            with st.expander(title):
                for position in batch["positions"]:
                    st.markdown(f"**{position['bundle_name']}**")
                    st.caption(f"Catalogue: {position['code']}")
                    for item in position["files"]:
                        cols = st.columns([3, 1.5, 1.5, 1])
                        cols[0].write(item["file_name"])
                        cols[1].write(f"{item['size_kb']:.1f} KB")
                        cols[2].write(item["saved_at"])

                        path = Path(item["file_path"])
                        if path.exists():
                            cols[3].download_button(
                                "Download",
                                data=path.read_bytes(),
                                file_name=path.name,
                                mime=_mime_type_for(path),
                                key=f"status-dl-{batch['id']}-{position['code']}-{item['doc_type']}",
                            )
                        else:
                            cols[3].write("Missing")

    st.markdown("### All Files On Disk")
    file_rows = _collect_download_file_rows(dl_path)
    if file_rows:
        st.dataframe(file_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No files downloaded yet.")

_render_hidden_flappy_game()
