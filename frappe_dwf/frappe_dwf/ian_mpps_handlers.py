"""
IAN & MPPS server-side processing helpers for the frappe_dwf app.

These functions encapsulate robust, idempotent ingestion and initial processing
of Instance Availability Notifications (IAN) and Modality Performed Procedure
Step (MPPS) payloads. They are intended to be called from the public API
endpoints (e.g., frappe_dwf.api.receive_ian / create_pps) or from webhook adapters.

Key features:
- Idempotent ingestion (unique ID checks)
- Basic payload validation
- Optional HMAC signature verification (uses site config key `dwf_api_secret`)
- Creation/updating of DocTypes: Instance Availability Notification, SOPInstance,
  Performed Procedure Step, Scheduled Procedure Step (status update)
- Safe enqueueing of background workers for heavier processing
- Error handling and logging
"""

import json
import hmac
import hashlib
import frappe
from frappe import _

from . import handlers as enqueue_handlers
from . import utils

# Config keys (in site_config.json or frappe.conf)
API_SECRET_CONF_KEY = "dwf_api_secret"
API_KEY_CONF_KEY = "dwf_api_key"  # already used elsewhere


# ---- Security helpers -----------------------------------------------------
def verify_signature(headers: dict, body_bytes: bytes) -> bool:
    """
    Verify HMAC-SHA256 signature against configured secret.
    Expects header 'X-Signature' with value 'sha256=<hex>'.
    Returns True if no secret configured (convenience for dev) or if signature matches.
    """
    secret = frappe.get_conf().get(API_SECRET_CONF_KEY)
    if not secret:
        # No secret configured -> allow (development convenience)
        return True

    sig_header = headers.get("X-Signature") or headers.get("X-Hub-Signature")
    if not sig_header:
        frappe.log_error("Missing signature header for IAN/MPPS request", "frappe_dwf.signature")
        return False

    # support 'sha256=...' and raw hex
    if sig_header.startswith("sha256="):
        sig = sig_header.split("=", 1)[1]
    else:
        sig = sig_header

    mac = hmac.new(secret.encode("utf-8"), msg=body_bytes, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    valid = hmac.compare_digest(expected, sig)
    if not valid:
        frappe.log_error("Invalid signature for IAN/MPPS request", "frappe_dwf.signature")
    return valid


# ---- IAN processing -------------------------------------------------------
def ingest_ian(payload: dict, request_headers: dict = None):
    """
    Ingest an Instance Availability Notification payload.

    Expected payload example:
    {
      "ian_id": "IAN-20251114-0001",
      "source": "OrthancAE",
      "sop_instance_uids": ["1.2.3.4", "..."],
      "availability_status": "Available",
      "timestamp": "2025-11-14T16:00:00Z",
      "patient_id": "P12345",                # optional
      "accession_number": "ACC-9876"         # optional
    }

    Returns a dict with status and ian_id.
    """
    body_bytes = json.dumps(payload).encode("utf-8")
    if request_headers and not verify_signature(request_headers, body_bytes):
        frappe.throw(_("Forbidden: invalid signature"), frappe.Forbidden)

    ian_id = payload.get("ian_id")
    if not ian_id:
        frappe.throw(_("IAN payload missing required field: ian_id"))

    # Idempotency: if IAN exists and processed, return immediately
    exists = frappe.get_all("Instance Availability Notification", filters={"ian_id": ian_id}, limit_page_length=1)
    if exists:
        # Optionally return existing doc name or status
        return {"status": "exists", "ian_id": ian_id}

    # Normalize SOP UIDs
    uids = utils.normalize_uids(payload.get("sop_instance_uids") or payload.get("sop_uids"))

    try:
        # Insert IAN doc
        doc = frappe.get_doc(
            {
                "doctype": "Instance Availability Notification",
                "ian_id": ian_id,
                "source": payload.get("source") or "",
                "sop_instance_uids": uids,
                "availability_status": payload.get("availability_status", "Available"),
                "timestamp": payload.get("timestamp") or frappe.utils.now(),
            }
        )
        doc.insert(ignore_permissions=True)

        # For each SOP UID, ensure SOPInstance exists and populate optional metadata
        patient_id = payload.get("patient_id")
        accession = payload.get("accession_number")
        for uid in utils.split_uids(uids):
            utils.get_or_create_sopinstance(uid, stored_at_aet=payload.get("source"), patient_id=patient_id, accession_number=accession)

        # Enqueue background processing to match SOPInstances to RPs and update worklists
        enqueue_handlers.enqueue_process_ian(ian_id=ian_id)

        return {"status": "created", "ian_id": ian_id}
    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title=f"ingest_ian failed for {ian_id}")
        raise


# ---- MPPS (Performed Procedure Step) processing ---------------------------
def ingest_mpps(payload: dict, request_headers: dict = None):
    """
    Ingest a modality MPPS payload.

    Expected payload example:
    {
      "pps_uid": "MPPS-20251114-0001",
      "sps_uid": "SPS-0001",          # optional
      "rp_id": "RP-0001",             # optional
      "actor": "CT-Scanner-1",
      "status": "COMPLETED",
      "instance_uids": ["1.2.3.4", "..."],
      "patient_id": "P12345",         # optional: helps matching
      "accession_number": "ACC-9876"  # optional
    }

    Returns dict with status and pps_uid.
    """
    body_bytes = json.dumps(payload).encode("utf-8")
    if request_headers and not verify_signature(request_headers, body_bytes):
        frappe.throw(_("Forbidden: invalid signature"), frappe.Forbidden)

    pps_uid = payload.get("pps_uid")
    if not pps_uid:
        frappe.throw(_("MPPS payload missing required field: pps_uid"))

    # Idempotency: skip if PPS already ingested
    exists = frappe.get_all("Performed Procedure Step", filters={"pps_uid": pps_uid}, limit_page_length=1)
    if exists:
        return {"status": "exists", "pps_uid": pps_uid}

    uids = utils.normalize_uids(payload.get("instance_uids"))

    try:
        # Insert PPS record
        pps_doc = frappe.get_doc(
            {
                "doctype": "Performed Procedure Step",
                "pps_uid": pps_uid,
                "sps": payload.get("sps_uid") or "",
                "rp": payload.get("rp_id") or "",
                "actor": payload.get("actor") or "",
                "status": payload.get("status", "COMPLETED"),
                "instance_uids": uids,
                "created_at": payload.get("created_at") or frappe.utils.now(),
            }
        )
        pps_doc.insert(ignore_permissions=True)

        # If SPS provided, update Scheduled Procedure Step status to Completed (idempotent)
        sps_uid = payload.get("sps_uid")
        if sps_uid:
            try:
                sps = frappe.get_doc("Scheduled Procedure Step", {"sps_uid": sps_uid})
                # Only change if not already Completed to avoid noisy writes
                if sps.status != "Completed":
                    sps.status = "Completed"
                    sps.save(ignore_permissions=True)
            except Exception:
                # Missing SPS is not fatal - log for debugging
                frappe.log_error(f"SPS {sps_uid} referenced by PPS {pps_uid} not found", "frappe_dwf.mpps")

        # Create SOPInstance entries for any listed UIDs, include optional metadata if present
        patient_id = payload.get("patient_id")
        accession = payload.get("accession_number")
        for uid in utils.split_uids(uids):
            utils.get_or_create_sopinstance(uid, stored_at_aet=payload.get("actor"), patient_id=patient_id, accession_number=accession)

        # Enqueue background processing
        enqueue_handlers.enqueue_process_pps(pps_uid=pps_uid)

        return {"status": "created", "pps_uid": pps_uid}
    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title=f"ingest_mpps failed for {pps_uid}")
        raise
