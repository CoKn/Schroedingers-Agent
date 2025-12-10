from fastmcp import FastMCP
import requests
import os
from dotenv import load_dotenv
from typing import Dict, Optional, List
import time

# -------------------------------------------------------------
# ENVIRONMENT
# -------------------------------------------------------------
load_dotenv()

SEC_API_KEY = os.getenv("SEC_API_KEY")
if not SEC_API_KEY:
    raise RuntimeError("Missing SEC_API_KEY")

# Two SEC bases:
SEC_DATA_BASE = "https://data.sec.gov"       # For JSON endpoints
SEC_ARCHIVES_BASE = "https://www.sec.gov"    # For actual filings (HTML/TXT) — extractor requires this

EXTRACTOR = "https://api.sec-api.io/extractor"

HEADERS = {
    "User-Agent": "StrategyExtractor/1.0 (contact: uniproject@student.unisg.ch)"
}

mcp = FastMCP(name="Corporate Strategy Extractor", json_response=True)


# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def sec_json(path: str) -> dict:
    """Retrieve SEC JSON endpoints from data.sec.gov."""
    url = f"{SEC_DATA_BASE}{path}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def url_exists(url: str) -> bool:
    """Check if a filing document actually exists."""
    r = requests.head(url, headers=HEADERS, allow_redirects=True)
    return r.status_code == 200


def find_primary_doc_fallback(cik: str, accession: str) -> Optional[str]:
    """
    Fallback: inspect the filing index.json and pick the primary .htm/.txt.
    """
    acc_clean = accession.replace("-", "")
    idx_url = f"{SEC_DATA_BASE}/Archives/edgar/data/{cik}/{acc_clean}/index.json"

    try:
        r = requests.get(idx_url, headers=HEADERS)
        if r.status_code != 200:
            return None
        items = r.json().get("directory", {}).get("item", [])
    except Exception:
        return None

    # Choose the first HTML/TXT file
    for f in items:
        name = f.get("name", "").lower()
        if name.endswith(".htm") or name.endswith(".html") or name.endswith(".txt"):
            # NOTE: must use www.sec.gov for extractor API
            return f"{SEC_ARCHIVES_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{f['name']}"

    return None


def extract_item(url: str, item: str) -> Optional[str]:
    """Extract a section via SEC Extractor API."""
    params = {
        "url": url,
        "item": item,
        "type": "text",
        "token": SEC_API_KEY
    }

    for _ in range(2):  # retry once if "processing"
        r = requests.get(EXTRACTOR, params=params)
        r.raise_for_status()
        text = r.text.strip()

        # If extractor returns content (not "processing")
        if not text.lower().startswith("processing"):
            # Sometimes extractor returns empty string
            return text if text.strip() else None

        time.sleep(1)

    return None


def build_url(cik: str, accession: str, doc: str) -> str:
    """Build SEC filing URL - must be on www.sec.gov."""
    acc_clean = accession.replace("-", "")
    return f"{SEC_ARCHIVES_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{doc}"


# -------------------------------------------------------------
# TOOL: extract_strategy
# -------------------------------------------------------------
@mcp.tool()
def extract_strategy(cik: str, limit: int = 2) -> Dict:
    """
    Extract strategy-relevant sections from recent filings.

    Strategy sources:
      • 10-K → Item 1 (Business), Item 7 (MD&A)
      • 10-Q → Part I Item 2 (MD&A)

    Steps:
      • Load CIK submissions
      • Find latest 10-K and 10-Qs
      • Resolve primary filing documents
      • Extract required strategic sections using SEC Extractor
    """

    cik_raw = str(cik).lstrip("0")
    cik_padded = cik_raw.zfill(10)

    subs = sec_json(f"/submissions/CIK{cik_padded}.json")
    recent = subs.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings: List = []

    # Identify available filings
    for form, acc, doc in zip(forms, accessions, primary_docs):
        if form not in ("10-K", "10-Q"):
            continue
        filings.append((form, acc, doc))
        if len(filings) >= limit:
            break

    results = {}
    meta = []

    for form, acc, doc in filings:

        # Try primary document directly
        url = build_url(cik_raw, acc, doc)

        # If missing, try fallback
        if not url_exists(url):
            fallback = find_primary_doc_fallback(cik_raw, acc)

            if fallback and url_exists(fallback):
                url = fallback
            else:
                meta.append({
                    "form": form,
                    "accession": acc,
                    "primary_document": doc,
                    "document_url": None,
                    "error": "Primary document not found"
                })
                continue

        filing_meta = {
            "form": form,
            "accession": acc,
            "primary_document": doc,
            "document_url": url
        }

        # Map strategy items
        if form == "10-K":
            items = {
                "business_overview": "1",
                "mdna": "7"
            }
        else:  # 10-Q
            items = {
                "mdna": "part1item2"
            }

        # Extract each strategic item
        extracted = {}
        for label, item_code in items.items():
            text = extract_item(url, item_code)
            if text:
                extracted[label] = text
            else:
                filing_meta.setdefault("extraction_errors", {})[label] = "empty_or_failed"

        results[acc] = extracted
        meta.append(filing_meta)

    return {
        "cik": cik_raw,
        "filings_analyzed": meta,
        "strategy_sections": results
    }


# -------------------------------------------------------------
# Run MCP server
# -------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8084
    )
