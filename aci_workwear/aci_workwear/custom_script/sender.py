import time

import frappe
import requests
from frappe.utils import add_to_date, get_datetime, now

from aci_workwear.aci_workwear.doctype.sync_log.sync_log import create_sync_up_log


BATCH_SIZE = 500
REQUEST_TIMEOUT = 600

# How many "hops" of Link/Dynamic Link fields to follow when pulling in
# dependencies. Safety net on top of EXCLUDED_LINK_DOCTYPES so a single
# push can never spider out into the entire database.
MAX_LINK_DEPTH = 20

# Overlap window applied on top of last_synced_on so a record saved in the
# same window a push runs is never missed due to clock/commit timing.
SYNC_OVERLAP_HOURS = 1

# Framework / system DocTypes that should never be auto-pulled in as a
# "linked master". Add your own business exclusions here as needed.
EXCLUDED_LINK_DOCTYPES = frozenset({
    "User", "Role", "Role Profile", "Has Role",
    "DocType", "DocField", "DocPerm",
    "Custom Field", "Property Setter", "Custom DocPerm",
    "Client Script", "Server Script",
    "Print Format", "Report", "Dashboard", "Dashboard Chart",
    "Workflow", "Workflow State", "Workflow Action Master",
    "Module Def", "File", "Email Account", "Email Template",
    "Notification", "Letter Head", "System Settings",
    "Domain", "Portal Settings", "Sync Setting",
    "Sync Up Configuration", "Sync Up Filter", "Sync Log",
})

LAYOUT_FIELDTYPES = frozenset({"Section Break", "Column Break", "Tab Break", "Button", "HTML", "Heading"})
SENSITIVE_FIELDTYPES = frozenset({"Password"})
FILE_FIELDTYPES = frozenset({"Attach", "Attach Image", "Signature"})
SKIP_SERIALIZE_FIELDTYPES = LAYOUT_FIELDTYPES | SENSITIVE_FIELDTYPES | FILE_FIELDTYPES

TABLE_FIELDTYPES = frozenset({"Table", "Table MultiSelect"})

# Standard (non-meta) fields worth carrying across so the receiver ends up
# with a faithful copy, including submitted status.
STANDARD_SYNC_FIELDS = ("owner", "creation", "docstatus", "idx")

MAX_HTTP_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def _log_error(title, message):
    """
    Wrapper around frappe.log_error that always uses explicit keyword
    arguments (the positional argument order for log_error changed between
    Frappe versions) and keeps the title within the Error Log title length.
    """

    frappe.log_error(title=title[:140], message=message)

def on_document_submit(doc, method=None):
    """
    Wired up in hooks.py as a wildcard doc_events "on_submit" handler - runs
    for every doctype's submit. Cheap early-exit if nothing is configured
    for this doctype. Enqueues the actual push only AFTER the submit
    transaction commits, so it never pushes a pre-submit/stale version.
    """

    if doc.doctype in EXCLUDED_LINK_DOCTYPES:
        return

    config = get_matching_sync_on_submit_config(doc.doctype)

    if not config:
        return

    doctype = doc.doctype
    docname = doc.name
    config_name = config.name

    def _enqueue():
        frappe.enqueue(
            "aci_workwear.aci_workwear.custom_script.sender.push_single_document",
            queue="short",
            timeout=REQUEST_TIMEOUT + 60,
            doctype=doctype,
            docname=docname,
            config_name=config_name,
        )

    frappe.db.after_commit(_enqueue)

def push_single_document(doctype, docname, config_name):
    """
    Background job body for the sync-on-submit trigger. Pushes one document
    (plus its resolved dependencies) immediately, using the exact same
    build/push pipeline as the scheduled Push. Does NOT touch that
    configuration's last_synced_on - the scheduled Push remains the
    authoritative catch-up mechanism.
    """
 
    sync_up = frappe.get_cached_doc("Sync Setting")
 
    if not sync_up.enable:
        return
 
    try:
        config = frappe.get_doc("Sync Up Configuration", config_name)
    except frappe.DoesNotExistError:
        return
 
    if not config.enabled or not config.sync_on_submit or config.document != doctype:
        # configuration changed/disabled between enqueue and run - skip quietly
        return
 
    if not frappe.db.exists(doctype, docname):
        return
 
    credentials = get_credentials(sync_up)
 
    payload = build_batch_payload(
        records=[frappe._dict(name=docname)],
        doctype=doctype,
        config=config,
    )
 
    if not payload["records"]:
        return
 
    push_batch(payload=payload, credentials=credentials)

    
def get_matching_sync_on_submit_config(doctype):
    """
    First enabled Sync Up Configuration (by priority) for this doctype that
    has "Sync on Submit" checked, or None.
    """
 
    configs = frappe.get_all(
        "Sync Up Configuration",
        filters={"enabled": 1, "document": doctype, "sync_on_submit": 1},
        fields=["name", "document", "sync_child_tables", "sync_linked_masters"],
        order_by="priority asc, creation asc",
        limit_page_length=1,
    )
 
    return configs[0] if configs else None


def get_sync_configurations():
    """Get all enabled sync configurations, in priority order."""

    return frappe.get_all(
        "Sync Up Configuration",
        filters={"enabled": 1},
        fields=[
            "name", "document", "sync_child_tables", "sync_linked_masters",
            "priority", "last_synced_on",
        ],
        order_by="priority asc, creation asc",
    )


def get_doctype_filters(configuration):
    """
    Get the configured filters for a sync configuration from its
    "Sync Up Filter" child rows.
    """

    filters = []

    filter_rows = frappe.get_all(
        "Sync Up Filter",
        filters={"parent": configuration.name, "parenttype": "Sync Up Configuration"},
        fields=["fieldname", "operator", "value"],
        order_by="idx asc",
    )

    for row in filter_rows:
        if not row.fieldname:
            continue
        filters.append([row.fieldname, row.operator, row.value])

    return filters


def get_linked_document_references(doc, sync_child_tables=True):
    """
    Find all direct Link / Dynamic Link references from a document
    (and, optionally, from rows inside its child tables).
    """

    references = []
    meta = frappe.get_meta(doc.doctype)

    for field in meta.fields:
        fieldtype = field.fieldtype
        fieldname = field.fieldname

        if fieldtype == "Link":
            value = doc.get(fieldname)
            linked_doctype = field.options

            if not value or not linked_doctype:
                continue
            if linked_doctype in EXCLUDED_LINK_DOCTYPES:
                continue

            references.append({"doctype": linked_doctype, "name": value})

        elif fieldtype == "Dynamic Link":
            value = doc.get(fieldname)
            options_field = field.options

            if not value or not options_field:
                continue

            linked_doctype = doc.get(options_field)

            if not linked_doctype or linked_doctype in EXCLUDED_LINK_DOCTYPES:
                continue

            references.append({"doctype": linked_doctype, "name": value})

        elif fieldtype in TABLE_FIELDTYPES and sync_child_tables:
            for child in (doc.get(fieldname) or []):
                references.extend(
                    get_linked_document_references(child, sync_child_tables=True)
                )

    return references


def collect_linked_documents(doc, sync_child_tables=True, visited=None, collected=None, depth=0):
    """Recursively collect all linked documents, deepest dependency first."""

    if visited is None:
        visited = set()
    if collected is None:
        collected = {}

    document_key = (doc.doctype, doc.name)

    if document_key in visited:
        return collected

    visited.add(document_key)

    if depth >= MAX_LINK_DEPTH:
        _log_error(
            "Cloud Sync - Max Link Depth Reached",
            f"Stopped expanding dependencies at depth {depth} for "
            f"{doc.doctype} {doc.name}. Increase MAX_LINK_DEPTH if this "
            f"document tree is legitimately deeper than expected.",
        )
        return collected

    for reference in get_linked_document_references(doc, sync_child_tables=sync_child_tables):
        linked_doctype = reference.get("doctype")
        linked_name = reference.get("name")

        if not linked_doctype or not linked_name:
            continue

        linked_key = (linked_doctype, linked_name)

        if linked_key in visited:
            continue

        try:
            linked_doc = frappe.get_doc(linked_doctype, linked_name)
        except Exception:
            _log_error(
                "Cloud Sync - Linked Document Fetch Failed",
                f"DocType: {linked_doctype}\nName: {linked_name}\n\n{frappe.get_traceback()}",
            )
            continue

        collect_linked_documents(
            linked_doc,
            sync_child_tables=sync_child_tables,
            visited=visited,
            collected=collected,
            depth=depth + 1,
        )

        collected[linked_key] = linked_doc

    return collected


def build_dependency_records(root_doc, config):
    """Dependency-ordered list of documents, root document last."""

    all_documents = {}

    if config.sync_linked_masters:
        all_documents = collect_linked_documents(
            root_doc, sync_child_tables=bool(config.sync_child_tables)
        )

    all_documents[(root_doc.doctype, root_doc.name)] = root_doc

    return list(all_documents.values())

@frappe.whitelist()
def update_cloud_records():
    """
    Entry point called by enqueue_update_cloud_records(). For every enabled
    Sync Up Configuration, fetch matching (new or changed) records and push
    them. Advances that configuration's last_synced_on only if its whole
    run succeeded.
    """

    sync_up = frappe.get_cached_doc("Sync Setting")

    if not sync_up.enable:
        return {"status": "disabled"}

    configurations = get_sync_configurations()

    if not configurations:
        return {"status": "success", "message": "No sync configuration found"}

    credentials = get_credentials(sync_up)

    overall_failed = False
    summary = []

    for configuration in configurations:
        doctype = configuration.document
        filters = get_doctype_filters(configuration)

        records = get_records_to_sync(
            doctype=doctype,
            filters=filters,
            last_synced_on=configuration.get("last_synced_on"),
        )

        if not records:
            summary.append({"doctype": doctype, "records_found": 0})
            continue

        summary.append({"doctype": doctype, "records_found": len(records)})

        config_failed = process_records_in_batches(
            records=records,
            doctype=doctype,
            config=configuration,
            batch_size=BATCH_SIZE,
            credentials=credentials,
        )

        if config_failed:
            overall_failed = True
        else:
            frappe.db.set_value(
                "Sync Up Configuration",
                configuration.name,
                "last_synced_on",
                now(),
                update_modified=False,
            )
            frappe.db.commit()

    return {
        "status": "failed" if overall_failed else "success",
        "summary": summary,
    }


def get_records_to_sync(doctype, filters, last_synced_on=None):
    """
    Fetch names of records matching the configuration's own filters, plus
    (if this configuration has synced before) a modified-since filter with
    a safety overlap - this is what makes updates get picked up, not just
    brand-new records.
    """

    filters = list(filters)

    if last_synced_on:
        overlap_from = add_to_date(get_datetime(last_synced_on), hours=-SYNC_OVERLAP_HOURS)
        filters.append(("modified", ">=", overlap_from))

    validate_sync_filters(doctype, filters)

    return frappe.get_all(doctype, filters=filters, fields=["name"], order_by="creation asc")


def validate_sync_filters(doctype, filters):
    """Validate configured filters against DocType metadata."""

    meta = frappe.get_meta(doctype)

    valid_fields = {field.fieldname for field in meta.fields}
    valid_fields.update({"name", "creation", "modified", "owner", "modified_by", "docstatus"})

    for condition in filters:
        if not condition:
            continue

        fieldname = condition[0]

        if fieldname not in valid_fields:
            frappe.throw(f"Invalid filter field '{fieldname}' for DocType '{doctype}'")


def process_records_in_batches(records, doctype, config, batch_size, credentials):
    """Returns True if any batch for this configuration failed."""

    total_records = len(records)
    had_failure = False

    for start in range(0, total_records, batch_size):
        batch_records = records[start:start + batch_size]

        payload = build_batch_payload(records=batch_records, doctype=doctype, config=config)

        if not payload["records"]:
            continue

        success = push_batch(payload=payload, credentials=credentials)

        if not success:
            had_failure = True

    return had_failure


def build_batch_payload(records, doctype, config):
    """
    Build the complete batch payload in dependency order:
    deepest linked masters first, root documents last.
    """

    all_records = []
    processed = set()

    for record in records:
        try:
            root_doc = frappe.get_doc(doctype, record.name)
            documents = build_dependency_records(root_doc=root_doc, config=config)

            for doc in documents:
                key = (doc.doctype, doc.name)

                if key in processed:
                    continue

                processed.add(key)
                all_records.append(
                    serialize_document(doc, sync_child_tables=bool(config.sync_child_tables))
                )

        except Exception:
            _log_error(
                "Cloud Sync - Build Payload Failed",
                f"{doctype} - {record.name}\n\n{frappe.get_traceback()}",
            )

    return {"records": all_records}


def serialize_document(doc, sync_child_tables=True):
    """
    Serialize a document for transport.

    - Skips layout, Password, and file-attachment fields.
    - Includes docstatus/owner/creation/idx so the receiver can rebuild an
      accurate, correctly-submitted copy, and can tell created vs updated.
    """

    meta = frappe.get_meta(doc.doctype)
    data = {}

    for field in meta.fields:
        fieldtype = field.fieldtype
        fieldname = field.fieldname

        if fieldtype in SKIP_SERIALIZE_FIELDTYPES:
            continue

        if fieldtype in TABLE_FIELDTYPES:
            if not sync_child_tables:
                continue
            rows = doc.get(fieldname) or []
            data[fieldname] = [serialize_child_document(row) for row in rows]
        else:
            data[fieldname] = doc.get(fieldname)

    for fieldname in STANDARD_SYNC_FIELDS:
        data[fieldname] = doc.get(fieldname)

    data["doctype"] = doc.doctype
    data["name"] = doc.name

    return data


def serialize_child_document(child_doc):

    meta = frappe.get_meta(child_doc.doctype)
    data = {}

    for field in meta.fields:
        fieldtype = field.fieldtype
        fieldname = field.fieldname

        if fieldtype in SKIP_SERIALIZE_FIELDTYPES:
            continue

        if fieldtype in TABLE_FIELDTYPES:
            rows = child_doc.get(fieldname) or []
            data[fieldname] = [serialize_child_document(row) for row in rows]
        else:
            data[fieldname] = child_doc.get(fieldname)

    data["doctype"] = child_doc.doctype

    if child_doc.name:
        data["name"] = child_doc.name

    return data


def get_credentials(sync_up):
    """Get + validate API credentials once per synchronization cycle."""

    required_fields = ("url", "api_key")
    missing = [f for f in required_fields if not sync_up.get(f)]

    if missing:
        frappe.throw(
            "Sync Setting is missing required field(s): "
            + ", ".join(missing)
            + ". Please configure them before running Push."
        )

    # NOTE: the field is intentionally "api_secrete" (existing typo on the
    # DocType) - left as-is to avoid a schema migration.
    api_secret = sync_up.get_password("api_secrete", raise_exception=False)

    if not api_secret:
        frappe.throw("API Secret is not set in Sync Setting.")

    return {
        "url": sync_up.url.rstrip("/"),
        "api_key": sync_up.api_key,
        "api_secret": api_secret,
    }


def _post_with_retries(url, headers, data):
    """POST with a few retries on transient network errors."""

    last_exc = None

    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        try:
            return requests.post(url=url, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < MAX_HTTP_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise last_exc


def push_batch(payload, credentials):
    """
    Send one batch to the cloud site and process the result directly from
    the HTTP response - no callback endpoint involved.
    """

    url = (
        f"{credentials['url']}/api/method/"
        "club_twenty_one.club_twenty_one.custom_script.receiver.update_bulk_data"
    )

    try:
        response = _post_with_retries(
            url=url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"token {credentials['api_key']}:{credentials['api_secret']}",
            },
            data=frappe.as_json(payload),
        )
    except requests.RequestException:
        _log_error("Cloud Sync - Request Error", frappe.get_traceback())
        return False

    if response.status_code != 200:
        _log_error(
            "Cloud Sync - HTTP Error",
            f"HTTP Status: {response.status_code}\nURL: {url}\nResponse: {response.text[:1000]}",
        )
        return False

    res_json = parse_response(response)

    if not res_json:
        return False

    message = res_json.get("message", res_json)
    sync_at = message.get("sync_at", now())
    results = message.get("results", [])

    batch_failed = False

    NON_FAILURE_STATUSES = {"success", "exists", "updated", "updated_partial", "skipped"}

    for record in results:
        record_status = "Success" if record.get("status") in NON_FAILURE_STATUSES else "Failed"

        if record_status == "Failed":
            batch_failed = True

        create_sync_up_log(
            reference_doctype=record.get("doctype"),
            reference_name=record.get("name"),
            status=record_status,
            sync_at=sync_at,
            message=record.get("message"),
            receiver_url=credentials["url"],
            response_code=response.status_code,
            request_type="Post",
        )

    return not batch_failed


def parse_response(response):
    """Safely parse JSON response."""

    content_type = response.headers.get("Content-Type", "").lower()

    if "application/json" not in content_type:
        _log_error(
            "Cloud Sync - Non JSON Response",
            f"URL: {response.url}\nStatus: {response.status_code}\n"
            f"Content-Type: {content_type}\nResponse: {response.text[:1000]}",
        )
        return None

    try:
        return response.json()
    except ValueError:
        _log_error(
            "Cloud Sync - Invalid JSON",
            f"URL: {response.url}\nStatus: {response.status_code}\nResponse: {response.text[:1000]}",
        )
        return None