# edqmUSP

Download COA, MSDS and COO documents from EDQM and USP public websites, then optionally upload files to Yandex Disk.

## What Changed

- No login is required for EDQM or USP downloads.
- USP search now uses public catalogue APIs instead of deprecated search URLs.
- USP COA/MSDS downloads use direct static document links resolved from catalogue metadata.
- COO output is always a country-named `.txt` file (for example, `United_States.txt`).
- EDQM downloads are now direct HTTP downloads (no browser automation required).

## Features

- **EDQM downloads** - COA, MSDS, COO from [crs.edqm.eu](https://crs.edqm.eu/)
- **USP downloads** - COA, MSDS, COO from [store.usp.org](https://store.usp.org/)
- **COO country output** - COO is normalized to a country-named `.txt` file
- **Yandex Disk upload** - upload EDQM/USP download folders
- **Streamlit UI** - web interface
- **CLI** - scriptable command-line usage

## Setup

```bash
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Set `YDISK_TOKEN` in `.env` or put it in `ydisk_token.txt`.

## Usage

### Web UI

```bash
streamlit run app.py
```

### CLI

```bash
# Download from EDQM
python main.py edqm Y0001532 Y0001234

# Download from USP
python main.py usp 1134357

# Upload all downloads to Yandex Disk
python main.py upload

# Upload only EDQM downloads
python main.py upload edqm
```

## Project Structure

```
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
