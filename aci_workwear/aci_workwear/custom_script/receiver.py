
import json

import frappe
from frappe.utils import now

BATCH_SIZE = 500

# Defense in depth: even though the sender filters these out, never allow a
# push to create/overwrite these DocTypes on this site.
REJECTED_DOCTYPES = frozenset({
    "User", "Role", "Role Profile", "Has Role",
    "DocType", "DocField", "DocPerm",
    "Custom Field", "Property Setter", "Custom DocPerm",
    "Client Script", "Server Script",
    "Print Format", "Report", "Workflow",
    "Module Def", "File", "Email Account", "System Settings",
})


def _log_error(title, message):
    frappe.log_error(title=title[:140], message=message)


# ============================================================
# MAIN RECEIVER
# ============================================================

@frappe.whitelist()
def update_bulk_data():
    """
    Receive bulk documents pushed from the local site.

    Expected payload:
    {
        "records": [{"doctype": "...", "name": "...", ...}, ...],
        "callback_url": "...",
        "branch": "...",
        "auth_token": "...",
        "is_last_batch": true
    }

    Records are expected to already be ordered by the sender, deepest
    dependency first, root document last.
    """

    try:
        data = get_request_data()

        records = data.get("records", [])
        callback_url = data.get("callback_url")
        branch = data.get("branch")
        auth_token = data.get("auth_token")
        is_last_batch = data.get("is_last_batch", False)

        if not records:
            response = {
                "status": "success",
                "message": "No records received",
                "results": [],
                "sync_at": now(),
                "branch": branch,
                "auth_token": auth_token,
                "is_last_batch": is_last_batch,
            }
            send_callback(callback_url, response)
            return response

        results = process_records(records)

        response = {
            "status": "success" if not any(r.get("status") == "failed" for r in results) else "failed",
            "results": results,
            "sync_at": now(),
            "branch": branch,
            "auth_token": auth_token,
            "is_last_batch": is_last_batch,
        }

        send_callback(callback_url, response)

        return response

    except Exception:
        _log_error("Cloud Sync - Receiver Failed", frappe.get_traceback())
        return {"status": "failed", "message": "Receiver failed"}


# REQUEST DATA
def get_request_data():
    """Safely read JSON request body."""

    try:
        request_data = frappe.local.request.get_data()

        if not request_data:
            return {}

        if isinstance(request_data, bytes):
            request_data = request_data.decode("utf-8")

        return json.loads(request_data)

    except Exception:
        _log_error("Cloud Sync - Invalid Request JSON", frappe.get_traceback())
        frappe.throw("Invalid JSON request")


# PROCESS RECORDS
def process_records(records):
    """Process all received records, in the order they were sent."""

    return [process_single_document(document_data) for document_data in records]


# PROCESS SINGLE DOCUMENT
def process_single_document(document_data):
    """
    Create a single document if it does not already exist.
    Existing documents are NOT modified.
    """

    if not isinstance(document_data, dict):
        return {"status": "failed", "message": "Invalid document data"}

    doctype = document_data.get("doctype")
    name = document_data.get("name")

    if not doctype:
        return {"status": "failed", "doctype": None, "name": name, "message": "Missing doctype"}

    if not name:
        return {"status": "failed", "doctype": doctype, "name": None, "message": "Missing document name"}

    if doctype in REJECTED_DOCTYPES:
        return {
            "status": "failed",
            "doctype": doctype,
            "name": name,
            "message": f"DocType '{doctype}' is not allowed to be synced",
        }

    if not frappe.db.exists("DocType", doctype):
        return {
            "status": "failed",
            "doctype": doctype,
            "name": name,
            "message": f"DocType '{doctype}' does not exist",
        }

    if frappe.db.exists(doctype, name):
        return {
            "status": "exists",
            "doctype": doctype,
            "name": name,
            "message": "Document already exists",
        }

    # Strip Password-type fields defensively in case any slipped through
    # from the sender - never write incoming secrets into this site.
    _strip_password_fields(document_data, doctype)

    """ Insert as a draft first (docstatus 0), then submit separately below
    so before_submit/on_submit hooks and validations run normally instead
    of force-setting docstatus=1 directly on insert."""
    source_docstatus = document_data.get("docstatus") or 0
    document_data["docstatus"] = 0

    try:
        doc = frappe.get_doc(document_data)
        doc.insert(set_name=name, ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        frappe.db.rollback()
        _log_error(
            "Cloud Sync - Document Creation Failed",
            f"DocType: {doctype}\nName: {name}\n\n{frappe.get_traceback()}",
        )
        return {"status": "failed", "doctype": doctype, "name": name, "message": frappe.get_traceback()}

    if source_docstatus == 1:
        try:
            doc.submit()
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            _log_error(
                "Cloud Sync - Document Submit Failed",
                f"DocType: {doctype}\nName: {name}\n\n{frappe.get_traceback()}",
            )
            return {
                "status": "success",
                "doctype": doctype,
                "name": doc.name,
                "message": "Document created but could not be submitted - see Error Log",
            }

    return {
        "status": "success",
        "doctype": doctype,
        "name": doc.name,
        "message": "Document created successfully",
    }


def _strip_password_fields(document_data, doctype):
    """Remove any Password-fieldtype values from the incoming payload."""

    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return

    for field in meta.fields:
        if field.fieldtype == "Password" and field.fieldname in document_data:
            document_data.pop(field.fieldname, None)


def send_callback(callback_url, response_data):
    """Send synchronization result back to the sender."""

    if not callback_url:
        return

    try:
        import requests

        response = requests.post(callback_url, json=response_data, timeout=120)

        if response.status_code >= 400:
            _log_error(
                "Cloud Sync - Callback Failed",
                f"Callback URL: {callback_url}\nStatus: {response.status_code}\n"
                f"Response: {response.text[:1000]}",
            )

    except Exception:
        _log_error("Cloud Sync - Callback Request Failed", frappe.get_traceback())