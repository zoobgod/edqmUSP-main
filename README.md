# edqmUSP

`edqmUSP` automates document retrieval for EDQM and USP catalogue items.
It removes manual catalogue browsing by fetching `COA`, `MSDS`, and `COO` files directly, then organizing them for immediate download (single files, per-position ZIP, or batch ZIP).

## Why This Saves Time

Without automation, users typically search each catalogue item manually and open multiple pages to find `COA`, `MSDS`, and origin data.

This app does it in one run:

- Searches positions by catalogue code.
- Downloads available files directly from public endpoints.
- Applies standardized naming.
- Bundles results into downloadable ZIP files.
- Optionally uploads to Yandex Disk.

## What The App Can Do

### EDQM

- Search EDQM positions by exact catalogue code.
- Download `COA`, `MSDS`, and `COO` from EDQM public pages.
- If EDQM `MSDS` is missing, fallback to Sigma-Aldrich SDS URLs automatically.
- EDQM `COO` behavior:
  - Download the original COO document.
  - Detect country from document content.
  - Rename the COO file using country name while keeping original extension (typically `.pdf`).
  - Example: `France.pdf`.

### USP

- Search USP positions via public product/search APIs.
- Download `COA` and `MSDS` via public static/document links.
- USP `COO` behavior:
  - Create country text file only.
  - Example: `United States.txt`.

### Streamlit Web UI

- Download by source (`EDQM` / `USP`) and selected document types.
- Download individual files per position.
- Download per-position ZIP.
- Download batch ZIP containing nested ZIPs for each position.
- View batch history and downloaded files table.
- Clear download cache from UI.
- Optional Yandex Disk upload.
- Includes optional in-app Flappy-style mini game (`Play V-Bird` button).

### CLI

- Download from EDQM by one or many catalogue codes.
- Download from USP by one or many catalogue codes.
- Upload downloaded files to Yandex Disk.

## Requirements

- Python 3.10+
- Network access to:
  - `crs.edqm.eu`
  - `store.usp.org`
  - `static.usp.org`
  - `www.sigmaaldrich.com` (for EDQM MSDS fallback)

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

1. Copy environment template:
   ```bash
   cp .env.example .env
   ```
2. Set Yandex Disk token if you need uploads:
   - `YDISK_TOKEN` in `.env`, or
   - `ydisk_token.txt`

Note:
- EDQM and USP downloads do not require login credentials.

## Usage

### Web UI

```bash
streamlit run app.py
```

### CLI

```bash
# EDQM download
python main.py edqm Y0001532 G0400006

# USP download
python main.py usp 1134357

# Upload all downloaded files
python main.py upload

# Upload only EDQM files
python main.py upload edqm

# Upload only USP files
python main.py upload usp
```

## Output Structure

Downloads are saved under:

- `downloads/edqm/`
- `downloads/usp/`

Typical outputs:

- EDQM:
  - `<catalogue>_COA.pdf` (or EDQM-provided filename)
  - `<catalogue>_MSDS_sigma.pdf` (if Sigma fallback used)
  - `<Country>.pdf` (COO renamed by detected country)
- USP:
  - `<catalogue>_COA.pdf`
  - `<catalogue>_MSDS.pdf`
  - `<Country>.txt` (COO)

## Project Layout

```text
edqmUSP/
├── app.py
├── main.py
├── requirements.txt
├── .env.example
├── ydisk_token.txt
└── src/
    ├── config.py
    ├── downloaders/
    │   ├── edqm.py
    │   └── usp.py
    └── uploaders/
        └── ydisk.py
```
