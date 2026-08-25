# Copyright (c) 2026, Corenex and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SyncLog(Document):
	pass


def create_sync_up_log(
	reference_doctype,
	reference_name,
	status,
	sync_at,
	message=None,
	receiver_url=None,
	response_code=None,
	request_type=None,
):
	try:
		sync_log = frappe.new_doc("Sync Log")
		sync_log.request_type = request_type
		sync_log.doctype_name = reference_doctype
		sync_log.document_name = reference_name
		sync_log.sync_status = status
		sync_log.message = message
		sync_log.sync_at = sync_at
		sync_log.receiver_url = receiver_url
		sync_log.response_code = response_code
		sync_log.insert(ignore_permissions=True, ignore_links=True)
		frappe.db.commit()

	except Exception:
		# NOTE: use explicit title=/message= kwargs - positional args here
		# previously swallowed the real traceback (it ended up as the
		# 140-char title instead of the message body).
		frappe.log_error(
			title="create_sync_up_log Failed",
			message=(
				f"reference_doctype: {reference_doctype}\n"
				f"reference_name: {reference_name}\n\n"
				f"{frappe.get_traceback()}"
			),
		)