# edqmUSP

Download COA, MSDS and COO from EDQM and USP websites, then upload to Yandex Disk.

## Features

- **EDQM downloads** - COA, MSDS, COO from [crs.edqm.eu](https://crs.edqm.eu/)
- **COO country output** - COO is converted to a country-named `.txt` file (for example, `France.txt`)
- **USP downloads** - COA, MSDS from [store.usp.org](https://store.usp.org/)
- **Yandex Disk upload** - automatic upload of downloaded documents
- **Streamlit web UI** - browser-based interface for easy operation
- **CLI** - command-line interface for scripting and automation

## Setup

```bash
pip install -r requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

2. **Yandex Disk token**: Either set `YDISK_TOKEN` in `.env` or paste your token into `ydisk_token.txt`.
   Get a token at: https://yandex.ru/dev/disk/poligon/

3. Add your EDQM and USP login credentials to `.env`.

## Usage

### Web UI (Streamlit)

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
├── app.py                  # Streamlit web UI
├── main.py                 # CLI entry point
├── requirements.txt
├── .env.example            # Environment template
├── ydisk_token.txt         # YDisk token file (gitignored)
├── .gitignore
└── src/
    ├── config.py           # Configuration loader
    ├── browser.py          # Selenium browser factory
    ├── downloaders/
    │   ├── edqm.py         # EDQM document downloader
    │   └── usp.py          # USP document downloader
    └── uploaders/
        └── ydisk.py        # Yandex Disk uploader
```
