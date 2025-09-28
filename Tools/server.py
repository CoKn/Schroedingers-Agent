from fastmcp import FastMCP
from pathlib import Path
import re
import json, shutil
import os
import secrets
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------
# MCP server
# --------------------------------------------------------------------
mcp = FastMCP(
    name="Customer Support",
    json_response=True
)

# --------------------------------------------------------------------
# Paths & helpers
# --------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_PATH = MODULE_DIR / "shipping_status.json"
DEFAULT_LOG_PATH = MODULE_DIR / "messages.jsonl"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def _load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {"trackings": []}

    # Read with BOM-tolerant encoding
    with p.open("r", encoding="utf-8-sig") as f:
        content = f.read()

    if content.strip() == "":
        return {"trackings": []}

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Backup the bad file once, then start fresh
        backup = p.with_suffix(p.suffix + f".corrupt-" +
                               datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        try:
            shutil.copy2(p, backup)
        except Exception:
            pass
        return {"trackings": []}

def _save_json(path: str | Path, data: Dict[str, Any]) -> None:
    p = Path(path)
    _ensure_parent(p)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _gen_message_id() -> str:
    return f"msg_{secrets.token_hex(6)}"

def _gen_replacement_order_id(original_order_id: str, existing: List[Dict[str, Any]]) -> str:
    # count prior replacements tied to this original
    n = 1
    for t in existing:
        if t.get("original_order_id") == original_order_id:
            n += 1
    return f"R-{original_order_id}-{n}"

def _gen_tracking_number(carrier_code: str) -> str:
    # Lightweight mocks that look carrier-ish
    cc = (carrier_code or "").upper()
    if cc == "UPS":
        return "1Z" + secrets.token_hex(8).upper()
    if cc == "FEDEX":
        return "".join(["7"] + [str(secrets.randbelow(10)) for _ in range(13)])
    if cc == "GLS":
        return "GLS" + "".join([str(secrets.randbelow(10)) for _ in range(9)]) + "DE"
    # default DHL-style
    return "DHL" + "".join([str(secrets.randbelow(10)) for _ in range(9)]) + "DE"

def _render_template(tpl: str, vars: Dict[str, Any]) -> str:
    # handle {{#if key}}...{{/if}}
    def repl_if(m):
        key = m.group(1).strip()
        content = m.group(2)
        val = vars.get(key)
        return content if val else ""
    tpl = re.sub(r"\{\{#if\s+([^\}]+)\}\}([\s\S]*?)\{\{\/if\}\}", repl_if, tpl)
    # handle simple {{ key }}
    def repl_var(m):
        key = m.group(1).strip()
        return str(vars.get(key, ""))
    return re.sub(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", repl_var, tpl)

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    # Support trailing 'Z'
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None

# --------------------------------------------------------------------
# ---- Lost/delayed shipment ----
# 1) get status
# --------------------------------------------------------------------
@mcp.tool()
def track_shiping(
    order_id: Optional[str] = None,
    tracking_number: Optional[str] = None,
    path: str = str(DEFAULT_JSON_PATH),
):
    """
    Look up a shipment in shipping_status.json (module-relative by default).
    Provide exactly one of `order_id` or `tracking_number`.

    Returns:
      {
        "found": bool,
        "query": {...},
        "summary": {...},   # concise view
        "tracking": {...}   # full raw record from file (if found)
      }
    """
    # Validate input
    if bool(order_id) == bool(tracking_number):
        raise ValueError("Provide exactly one of `order_id` or `tracking_number`.")

    # Load file (gracefully handle missing by returning empty structure)
    data = _load_json(path)
    trackings = data.get("trackings", [])
    match = None

    # Find record
    for t in trackings:
        if order_id and t.get("order_id") == order_id:
            match = t
            break
        if tracking_number and t.get("tracking_number") == tracking_number:
            match = t
            break

    query = {"order_id": order_id, "tracking_number": tracking_number}

    if match is None:
        return {
            "found": False,
            "query": query,
            "message": "No matching shipment found.",
            "file": str(Path(path).resolve()),
            "cwd": str(Path.cwd()),
        }

    # Normalize last_scan_age_days if missing
    last_scan_age_days = match.get("last_scan_age_days")
    if last_scan_age_days is None and match.get("last_scan_time"):
        now = datetime.now(timezone.utc)
        last_scan_dt = _parse_iso(match.get("last_scan_time"))
        if last_scan_dt:
            last_scan_age_days = (now - last_scan_dt).total_seconds() / 86400.0

    # Build concise summary
    summary = {
        "order_id": match.get("order_id"),
        "tracking_number": match.get("tracking_number"),
        "carrier_code": match.get("carrier_code"),
        "status": match.get("status"),
        "delivered": match.get("delivered"),
        "eta": match.get("eta"),
        "last_scan_time": match.get("last_scan_time"),
        "last_scan_age_days": round(last_scan_age_days, 2) if isinstance(last_scan_age_days, (int, float)) else last_scan_age_days,
        "value_eur": match.get("value_eur"),
        "require_signature": match.get("require_signature"),
        "proof_of_delivery_url": match.get("proof_of_delivery_url"),
    }

    return {
        "found": True,
        "query": query,
        "file": str(Path(path).resolve()),
        "cwd": str(Path.cwd()),
        "summary": summary,
        "tracking": match,
    }

# --------------------------------------------------------------------
# 2) replace order (orders.createReplacement)
# --------------------------------------------------------------------
@mcp.tool()
def place_order(
    original_order_id: str,
    items: Optional[List[Dict[str, Any]]] = None,
    warehouse: Optional[str] = None,
    notes: Optional[str] = None,
    require_signature: Optional[bool] = None,
    carrier_code: str = "DHL",
    eta_days: int = 3,
    path: str = str(DEFAULT_JSON_PATH),
    idempotency_key: Optional[str] = None,
):
    """
    Create a replacement shipment for an existing order and persist it into shipping_status.json.
    - If `require_signature` is None, inherit from original or set True when value_eur >= 250.
    - Returns replacement_order_id, tracking_number, and a concise summary.
    """
    db = _load_json(path)
    trackings = db.get("trackings", [])

    # idempotency support
    db.setdefault("_idempotency", {})
    if idempotency_key and idempotency_key in db["_idempotency"]:
        return db["_idempotency"][idempotency_key]

    # find original
    original = next((t for t in trackings if t.get("order_id") == original_order_id), None)
    if original is None:
        raise ValueError(f"Original order_id not found: {original_order_id}")

    # derive values
    rep_order_id = _gen_replacement_order_id(original_order_id, trackings)
    carrier_code = carrier_code or original.get("carrier_code", "DHL")
    tracking_number = _gen_tracking_number(carrier_code)
    value_eur = original.get("value_eur", 0.0)
    if require_signature is None:
        require_signature = bool(original.get("require_signature")) or (value_eur >= 250.0)
    eta = (datetime.now(timezone.utc) + timedelta(days=eta_days)).isoformat()

    # replacement record
    new_record = {
        "order_id": rep_order_id,
        "original_order_id": original_order_id,
        "tracking_number": tracking_number,
        "carrier_code": carrier_code,
        "status": "label_created",
        "delivered": False,
        "eta": eta,
        "last_scan_time": None,
        "last_scan_age_days": None,
        "proof_of_delivery_url": None,
        "value_eur": value_eur,
        "require_signature": require_signature,
        "address_risk_score": original.get("address_risk_score", 0.0),
        "items": items if items is not None else original.get("items", []),
        "events": [
            {
                "timestamp": _now_iso(),
                "location": warehouse or "WH-DEFAULT",
                "status": "label_created",
                "code": "LABEL_CREATED",
                "description": f"Replacement created for {original_order_id}",
            }
        ],
        "notes": notes or "",
        "warehouse": warehouse or "WH-DEFAULT",
    }

    # persist
    trackings.append(new_record)
    db["trackings"] = trackings

    result = {
        "replacement_order_id": rep_order_id,
        "tracking_number": tracking_number,
        "carrier_code": carrier_code,
        "require_signature": require_signature,
        "created_at": _now_iso(),
        "eta": eta,
        "summary": {
            "status": new_record["status"],
            "warehouse": new_record["warehouse"],
            "value_eur": value_eur,
            "items": new_record["items"],
        },
    }

    if idempotency_key:
        db["_idempotency"][idempotency_key] = result

    _save_json(path, db)
    return result

# --------------------------------------------------------------------
# 3) notify customer (crm.notifyCustomer)
# --------------------------------------------------------------------
_TEMPLATES = {
    "delay-ack": {
        "subject": "Update on your order {{order_id}}",
        "body": (
            "We’re tracking your order {{order_id}}. The carrier shows a delay; "
            "latest ETA {{eta}}. I’m checking stock so we can either re-ship promptly "
            "or file a carrier claim."
        ),
    },
    "reshipped": {
        "subject": "Replacement on the way for {{original_order_id}}",
        "body": (
            "We’ve sent a replacement for {{original_order_id}}. "
            "New tracking: {{tracking_number}}. "
            "{{#if require_signature}}A signature will be required on delivery.{{/if}}"
        ),
    },
    "oos-options": {
        "subject": "Choose an option for your order {{order_id}}",
        "body": (
            "Your item is currently out of stock. Would you prefer (A) full refund now, "
            "or (B) an alternate color that’s available today?"
        ),
    },
    "porch-piracy-affidavit": {
        "subject": "Action needed: affidavit for order {{order_id}}",
        "body": (
            "The carrier marks the package as delivered on {{delivery_date}}, but you reported it missing. "
            "Please complete this brief affidavit ({{link}}) within {{window_days}} days so we can proceed "
            "with a re-ship or refund."
        ),
    },
    "refund-confirm": {
        "subject": "Refund issued for {{order_id}} ({{refund_id}})",
        "body": (
            "We’ve issued your refund ({{refund_id}}) for €{{amount}}. "
            "You’ll see it on your statement within 3–5 business days."
        ),
    },
    "signature-required": {
        "subject": "Signature required for delivery",
        "body": "Because your item is high-value, a delivery signature will be required.",
    },
    "case-closed": {
        "subject": "Your case {{case_id}} is now closed",
        "body": "Glad we could resolve this. If anything else comes up, just reply to this email.",
    },
}

@mcp.tool()
def send_message(
    case_id: str,
    channel: str = "email",           # e.g., "email", "sms", "in_app"
    template_id: str = "delay-ack",
    merge_vars: Optional[Dict[str, Any]] = None,
    to: Optional[str] = None,
    cc: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    log_path: str = str(DEFAULT_LOG_PATH),
    idempotency_key: Optional[str] = None,
):
    """
    Mock customer notification.
    - Renders a simple template with {{placeholders}} and {{#if flag}}...{{/if}} blocks.
    - Appends a JSON line to messages.jsonl (module-relative by default) for auditing.
    - Returns a message_id, subject, and body.
    """
    merge_vars = merge_vars or {}
    tpl = _TEMPLATES.get(template_id)
    if not tpl:
        raise ValueError(f"Unknown template_id: {template_id}")

    subject = _render_template(tpl["subject"], merge_vars)
    body = _render_template(tpl["body"], merge_vars)

    # Prepare log record
    message_id = _gen_message_id() if not idempotency_key else f"idemp_{idempotency_key}"
    record = {
        "message_id": message_id,
        "created_at": _now_iso(),
        "case_id": case_id,
        "channel": channel,
        "template_id": template_id,
        "to": to or "customer@example.com",
        "cc": cc or [],
        "attachments": attachments or [],
        "subject": subject,
        "body": body,
        "merge_vars": merge_vars,
    }

    # idempotency: if same key exists in log, don't duplicate
    log_p = Path(log_path)
    if idempotency_key and log_p.exists():
        with log_p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get("message_id") == message_id:
                        return obj
                except json.JSONDecodeError:
                    continue

    # append to log
    _ensure_parent(log_p)
    with log_p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record

# --------------------------------------------------------------------
# Misc example tool
# --------------------------------------------------------------------
@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

# --------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)
