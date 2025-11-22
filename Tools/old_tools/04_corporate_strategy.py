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

SEC_BASE = "https://data.sec.gov"
EXTRACTOR = "https://api.sec-api.io/extractor"
HEADERS = {
    "User-Agent": "StrategyExtractor/1.0 (contact: uniproject@student.unisg.ch)"
}

mcp = FastMCP(name="Corporate Strategy Extractor", json_response=True)


# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def sec_json(path: str) -> dict:
    url = f"{SEC_BASE}{path}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def url_exists(url: str) -> bool:
    """Check if a filing document actually exists on SEC servers."""
    r = requests.head(url, headers=HEADERS)
    return r.status_code == 200


def find_primary_doc_fallback(cik: str, accession: str) -> Optional[str]:
    """
    Fallback method: read index.json and choose the REAL .htm/.txt filing doc.
    """
    acc_clean = accession.replace("-", "")
    idx_url = f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc_clean}/index.json"

    try:
        r = requests.get(idx_url, headers=HEADERS)
        if r.status_code != 200:
            return None
        items = r.json().get("directory", {}).get("item", [])
    except Exception:
        return None

    for f in items:
        name = f.get("name", "").lower()
        if name.endswith(".htm") or name.endswith(".html") or name.endswith(".txt"):
            return f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{f['name']}"

    return None


def extract_item(url: str, item: str) -> Optional[str]:
    """Extract a strategic section via SEC Extractor API."""
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

        if not text.lower().startswith("processing"):
            return text

        time.sleep(1)

    return None


def build_url(cik: str, accession: str, doc: str) -> str:
    acc_clean = accession.replace("-", "")
    return f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{doc}"


# -------------------------------------------------------------
# TOOL: extract_strategy
# -------------------------------------------------------------
@mcp.tool()
def extract_strategy(cik: str, limit: int = 2) -> Dict:
    """
    Extract ONLY strategy-related sections from recent filings.

    Strategy sources:
      • 10-K → Item 1 (Business), Item 7 (MD&A)
      • 10-Q → Part I Item 2 (MD&A)

    Automatically:
      • Validates filing documents
      • Skips missing or future filings
      • Uses index.json fallback when needed
    """

    cik_raw = str(cik).lstrip("0")
    cik_padded = cik_raw.zfill(10)

    subs = sec_json(f"/submissions/CIK{cik_padded}.json")
    recent = subs.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings: List = []

    # Identify latest valid filings
    for form, acc, doc in zip(forms, accessions, primary_docs):
        if form not in ("10-K", "10-Q"):
            continue
        filings.append((form, acc, doc))
        if len(filings) >= limit:
            break

    results = {}
    meta = []

    for form, acc, doc in filings:

        # Attempt primaryDocument URL first
        url = build_url(cik_raw, acc, doc)

        # Validate existence
        if not url_exists(url):
            # Try fallback discovery via index.json
            fallback = find_primary_doc_fallback(cik_raw, acc)
            if fallback and url_exists(fallback):
                url = fallback
            else:
                # Skip broken filing
                meta.append({
                    "form": form,
                    "accession": acc,
                    "document_url": None,
                    "error": "Primary document not found"
                })
                continue

        meta.append({
            "form": form,
            "accession": acc,
            "document_url": url
        })

        # Item map for strategy-only extraction
        if form == "10-K":
            items = {
                "business_overview": "1",
                "mdna": "7"
            }
        else:  # 10-Q
            items = {
                "mdna": "part1item2"
            }

        for label, item_code in items.items():
            if label not in results:
                text = extract_item(url, item_code)
                if text:
                    results[label] = text

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
        port=8087
    )
