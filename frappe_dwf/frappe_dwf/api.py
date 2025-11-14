import frappe
from frappe import _

@frappe.whitelist(allow_guest=True)
def receive_ian(ian_id=None, source=None, sop_uids=None, availability_status='Available'):
    """Receive an Instance Availability Notification (IAN) from a PACS/gateway.
    Expects sop_uids as comma-separated list of SOP Instance UIDs."""
    if not ian_id:
        frappe.throw("ian_id is required")
    existing = frappe.get_all('Instance Availability Notification', filters={'ian_id': ian_id})
    if existing:
        return {'status': 'exists', 'ian_id': ian_id}
    doc = frappe.get_doc({
        'doctype': 'Instance Availability Notification',
        'ian_id': ian_id,
        'source': source or '',
        'sop_instance_uids': sop_uids or '',
        'availability_status': availability_status,
        'timestamp': frappe.utils.now()
    })
    doc.insert(ignore_permissions=True)

    # create or update SOPInstance records for each SOP UID
    if sop_uids:
        for uid in [u.strip() for u in sop_uids.split(',') if u.strip()]:
            existing_si = frappe.get_all('SOPInstance', filters={'sop_uid': uid})
            if not existing_si:
                si = frappe.get_doc({
                    'doctype': 'SOPInstance',
                    'sop_uid': uid,
                    'stored_at_aet': source or '',
                    'created_at': frappe.utils.now()
                })
                si.insert(ignore_permissions=True)
    # enqueue a background job to notify worklist managers or update worklists
    frappe.enqueue('frappe_dwf.api._process_ian', ian_id=ian_id, queue='default')
    return {'status': 'created', 'ian_id': ian_id}


def _process_ian(ian_id=None):
    """Background worker to process IAN and update worklist items/statuses."""
    try:
        ian = frappe.get_doc('Instance Availability Notification', {'ian_id': ian_id})
    except Exception:
        return
    uids = [u.strip() for u in (ian.sop_instance_uids or '').split(',') if u.strip()]
    # naive matching: find WorklistItems referencing RPs that expect these instances; real logic should be more complex
    for uid in uids:
        # find SOPInstance -> see if any Requested Procedure should be updated
        sis = frappe.get_all('SOPInstance', filters={'sop_uid': uid}, fields=['name'])
        # placeholder: additional matching and notifications
    # TODO: implement matching of SOPInstances to RPs and clear partial_data_flags

@frappe.whitelist(allow_guest=True)
def create_pps(pps_uid=None, sps_uid=None, rp_id=None, actor=None, status='COMPLETED', instance_uids=''):
    """Create/ingest a Performed Procedure Step (MPPS) record."""
    if not pps_uid:
        frappe.throw('pps_uid is required')
    existing = frappe.get_all('Performed Procedure Step', filters={'pps_uid': pps_uid})
    if existing:
        return {'status': 'exists', 'pps_uid': pps_uid}
    doc = frappe.get_doc({
        'doctype': 'Performed Procedure Step',
        'pps_uid': pps_uid,
        'sps': sps_uid or '',
        'rp': rp_id or '',
        'actor': actor or '',
        'status': status,
        'instance_uids': instance_uids or '',
        'created_at': frappe.utils.now()
    })
    doc.insert(ignore_permissions=True)
    frappe.enqueue('frappe_dwf.api._process_pps', pps_uid=pps_uid, queue='default')
    return {'status': 'created', 'pps_uid': pps_uid}


def _process_pps(pps_uid=None):
    try:
        pps = frappe.get_doc('Performed Procedure Step', {'pps_uid': pps_uid})
    except Exception:
        return
    # Update SPS and Requested Procedure status as needed
    if pps.sps:
        try:
            sps = frappe.get_doc('Scheduled Procedure Step', {'sps_uid': pps.sps})
            sps.status = 'Completed' if pps.status == 'COMPLETED' else sps.status
            sps.save(ignore_permissions=True)
        except Exception:
            pass
    # If instance_uids provided, create SOPInstance records
    for uid in [u.strip() for u in (pps.instance_uids or '').split(',') if u.strip()]:
        if not frappe.get_all('SOPInstance', filters={'sop_uid': uid}):
            frappe.get_doc({
                'doctype': 'SOPInstance',
                'sop_uid': uid,
                'created_at': frappe.utils.now()
            }).insert(ignore_permissions=True)
    # enqueue IAN creation or further processing if needed

@frappe.whitelist(allow_guest=True)
def create_ups(ups_id=None, rp_id=None, ups_status='SCHEDULED', actor=None, instance_uids=''):
    """Create/ingest a Unified Procedure Step (DICOM UPS) record."""
    if not ups_id:
        frappe.throw('ups_id is required')
    existing = frappe.get_all('Unified Procedure Step', filters={'ups_id': ups_id})
    if existing:
        return {'status': 'exists', 'ups_id': ups_id}
    doc = frappe.get_doc({
        'doctype': 'Unified Procedure Step',
        'ups_id': ups_id,
        'rp': rp_id or '',
        'ups_status': ups_status,
        'actor': actor or '',
        'instance_uids': instance_uids,
        'start_time': frappe.utils.now() if ups_status == 'IN-PROGRESS' else None,
        'end_time': frappe.utils.now() if ups_status in ('COMPLETED','FAILED','CANCELLED') else None
    })
    doc.insert(ignore_permissions=True)
    # if completed and instance list present, create SOPInstance records
    if instance_uids and ups_status == 'COMPLETED':
        for uid in [u.strip() for u in instance_uids.split(',') if u.strip()]:
            if not frappe.get_all('SOPInstance', filters={'sop_uid': uid}):
                frappe.get_doc({
                    'doctype': 'SOPInstance',
                    'sop_uid': uid,
                    'created_at': frappe.utils.now()
                }).insert(ignore_permissions=True)
    return {'status': 'created', 'ups_id': ups_id}

@frappe.whitelist()
def get_worklist(manager=None, user=None):
    """Return a list of Worklist Items for a given manager and/or user."""
    filters = {}
    if manager:
        filters['worklist_manager'] = manager
    if user:
        filters['assigned_to'] = user
    items = frappe.get_all('Worklist Item', filters=filters, fields=['name','worklist_id','rp','assigned_to','status','partial_data_flag'])
    return items
