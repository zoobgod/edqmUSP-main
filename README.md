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
- Fall back to the server-rendered USP product state if the product API is unavailable or changes format.
- Use an honest HTTP client identity with retry handling (USP rejects incomplete browser impersonation at its edge).
- Download `COA` and `MSDS` via public static/document links.
- Validate PDF signatures before saving, so upstream error payloads are never packaged as documents.
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

### CLI

- Download from EDQM by one or many catalogue codes.
- Download from USP by one or many catalogue codes.
- Upload downloaded files to Yandex Disk.

### Vercel Web App

- Landing page on the root domain.
- Dedicated downloader page on the same domain.
- Dedicated bulk catalogue-finder page on the same domain.
- Copy-ready lookup output for catalogue numbers and full table data.
- Responsive, keyboard-accessible workflows with input counts, loading feedback, and accessible result tables.
- Built on FastAPI for Vercel deployment, while reusing the same EDQM/USP downloader logic.

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

### Vercel Deployment

This repository now includes:

- `api/index.py` - Vercel-compatible FastAPI entrypoint
- `vercel.json` - root rewrite configuration for same-domain routing
- `src/services/lookup.py` - shared lookup parsing/candidate generation
- `src/services/bundles.py` - shared ZIP/bundle helpers used by app surfaces

After pushing to Vercel, the main routes are:

- `/`
- `/download`
- `/lookup`

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
├── vercel.json
├── main.py
├── requirements.txt
├── .env.example
├── ydisk_token.txt
├── api/
│   └── index.py
└── src/
    ├── config.py
    ├── services/
    │   ├── bundles.py
    │   └── lookup.py
    ├── downloaders/
    │   ├── edqm.py
    │   └── usp.py
    └── uploaders/
        └── ydisk.py
```

## Tests

The repository includes narrow regression tests for:

- lookup candidate generation
- bundle/ZIP generation
- FastAPI lookup/download route behavior

Run them with:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```
