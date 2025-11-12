"""# frappe_dwf/api.py
# HL7 v2 adapter using hl7apy for parsing, with fallback to simple extraction.
import json
import frappe
from frappe import _
from frappe.utils import now

# try to import hl7apy; if missing, we'll fall back to regex fallback extractor
try:
    from hl7apy.parser import parse_message
    HL7APY_AVAILABLE = True
except Exception:
    HL7APY_AVAILABLE = False

import re
from types import SimpleNamespace

@frappe.whitelist(allow_guest=True)
def ihe_receive_message():
    """
    Accept inbound IHE message.
    - If content-type is application/json, expects { message_type, message_id, payload, source_actor, destination_actor }
    - Otherwise treats body as raw HL7v2 (text) and runs parser using hl7apy if available.
    Creates a Message DocType record and returns acceptance info.
    """
    try:
        raw = frappe.local.request.get_data(as_text=True) or ""
        content_type = (frappe.local.request.headers.get("Content-Type") or "").lower()

        if "application/json" in content_type:
            payload = json.loads(raw)
            msg = normalize_from_json(payload)
        else:
            # assume HL7 v2 text by default
            msg = normalize_hl7_v2(raw)

        # idempotency: if message with same message_id exists, return existing record
        existing = None
        if msg.get("message_id"):
            existing = frappe.db.get_all("Message", filters={"message_id": msg.get("message_id")}, fields=["name", "status", "message_id", "correlation_id"])
        if existing:
            result = existing[0]
            frappe.local.response.update({
                "status": "200",
                "message": "Message already exists",
                "data": {
                    "message_id": result.get("message_id"),
                    "status": result.get("status"),
                    "correlation_id": result.get("correlation_id")
                }
            })
            return frappe.local.response

        # create Message doc
        message_doc = frappe.get_doc({
            "doctype": "Message",
            "message_id": msg.get("message_id") or frappe.generate_hash(),
            "message_type": msg.get("message_type") or "UNKNOWN",
            "payload": msg.get("payload") or raw,
            "source": msg.get("source_actor"),
            "destination": msg.get("destination_actor"),
            "correlation_id": msg.get("correlation_id"),
            "status": "received",
            "received_at": now()
        })
        # persist ignoring permissions for adapter
        message_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        frappe.local.response.update({
            "status": "201",
            "message": "Message accepted and queued",
            "data": {
                "message_id": message_doc.message_id,
                "status": message_doc.status,
                "correlation_id": message_doc.correlation_id
            }
        })
        return frappe.local.response

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "frappe_dwf.ihe_receive_message")
        frappe.local.response.update({
            "status": "500",
            "message": "Failed to accept message",
            "error": str(e)
        })
        return frappe.local.response


def normalize_from_json(payload):
    """Simple pass-through normalizer for JSON input"""
    return {
        "message_id": payload.get("message_id"),
        "message_type": payload.get("message_type"),
        "payload": json.dumps(payload.get("payload")) if isinstance(payload.get("payload"), (dict, list)) else payload.get("payload"),
        "source_actor": payload.get("source_actor"),
        "destination_actor": payload.get("destination_actor"),
        "correlation_id": payload.get("correlation_id")
    }


def normalize_hl7_v2(raw):
    """
    HL7 v2 normalizer that uses hl7apy when available for robust parsing.
    Returns a dict with keys suitable for creating a Message DocType:
      - message_id, message_type, payload, source_actor, destination_actor, correlation_id
    If hl7apy parsing fails, falls back to a safe regex-based extraction.
    """
    if not raw:
        return {
            "message_id": frappe.generate_hash(),
            "message_type": "UNKNOWN",
            "payload": raw,
            "source_actor": None,
            "destination_actor": None,
            "correlation_id": None
        }

    # Prefer hl7apy if available
    if HL7APY_AVAILABLE:
        try:
            msg = parse_message(raw, find_groups=False)
            # safe getters: try multiple access patterns and fall back to regex if necessary
            def _safe_get_segment_field(seg_name, field_name, fallback=None):
                try:
                    # try attribute access like msg.MSH.msh_9
                    seg = getattr(msg, seg_name)
                    field = getattr(seg, field_name)
                    # .to_er7() is a robust textual representation (components included)
                    return field.to_er7() if hasattr(field, "to_er7") else str(field)
                except Exception:
                    try:
                        # try via segment() list accessor
                        segs = msg.segment(seg_name)
                        if segs:
                            seg0 = segs[0]
                            field = getattr(seg0, field_name)
                            return field.to_er7() if hasattr(field, "to_er7") else str(field)
                    except Exception:
                        return fallback

            message_type = _safe_get_segment_field("MSH", "msh_9", None)
            message_id = _safe_get_segment_field("MSH", "msh_10", None)
            sending_app = _safe_get_segment_field("MSH", "msh_3", None)
            sending_fac = _safe_get_segment_field("MSH", "msh_4", None)
            receiving_app = _safe_get_segment_field("MSH", "msh_5", None)
            receiving_fac = _safe_get_segment_field("MSH", "msh_6", None)

            def combine(a, b):
                if a and b:
                    return f"{a}|{b}"
                return a or b

            source_actor = combine(sending_app, sending_fac)
            destination_actor = combine(receiving_app, receiving_fac)

            # correlation: prefer ORC-2 (order control id), else PID-3 (patient id)
            correlation_id = None
            try:
                correlation_id = _safe_get_segment_field("ORC", "orc_2", None)
            except Exception:
                correlation_id = None
            if not correlation_id:
                correlation_id = _safe_get_segment_field("PID", "pid_3", None)

            return {
                "message_id": message_id or frappe.generate_hash(),
                "message_type": message_type or "UNKNOWN",
                "payload": raw,
                "source_actor": source_actor,
                "destination_actor": destination_actor,
                "correlation_id": correlation_id
            }
        except Exception:
            # fall-through to regex fallback
            pass

    # Fallback: naive regex-based extraction (keeps earlier behavior if hl7apy not installed)
    segments = re.split(r'\r\n?|\n', raw.strip())
    seg_map = {}
    for seg in segments:
        if not seg:
            continue
        parts = seg.split("|")
        name = parts[0]
        seg_map.setdefault(name, []).append(parts)

    def get_field(seg_name, seg_index, field_idx, component_idx=None):
        try:
            segs = seg_map.get(seg_name)
            if not segs:
                return None
            seg = segs[seg_index]
            val = seg[field_idx] if field_idx < len(seg) else None
            if val and component_idx is not None:
                comps = val.split("^")
                return comps[component_idx] if component_idx < len(comps) else val
            return val
        except Exception:
            return None

    msh = seg_map.get("MSH", [[None]])[0] if seg_map.get("MSH") else []
    message_type = None
    message_id = None
    source_actor = None
    destination_actor = None
    correlation_id = None

    if msh:
        if len(msh) > 8:
            message_type = msh[8]
        if len(msh) > 9:
            message_id = msh[9]
        sending_app = msh[2] if len(msh) > 2 else None
        sending_fac = msh[3] if len(msh) > 3 else None
        receiving_app = msh[4] if len(msh) > 4 else None
        receiving_fac = msh[5] if len(msh) > 5 else None
        def combine(a, b):
            if a and b:
                return f"{a}|{b}"
            return a or b
        source_actor = combine(sending_app, sending_fac)
        destination_actor = combine(receiving_app, receiving_fac)

    orc = seg_map.get("ORC", [[None]])
    if orc and orc[0] and len(orc[0]) > 1:
        correlation_id = orc[0][1]
    else:
        pid = seg_map.get("PID", [[None]])
        if pid and pid[0] and len(pid[0]) > 3:
            correlation_id = pid[0][3] if len(pid[0]) > 3 else pid[0][2]

    return {
        "message_id": message_id or frappe.generate_hash(),
        "message_type": message_type or "UNKNOWN",
        "payload": raw,
        "source_actor": source_actor,
        "destination_actor": destination_actor,
        "correlation_id": correlation_id
    }
"""