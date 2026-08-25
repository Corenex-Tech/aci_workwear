# Copyright (c) 2026, Corenex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SyncSetting(Document):
	pass


@frappe.whitelist()
def enqueue_update_cloud_records():

	if not frappe.has_permission("Sync Setting", "write"):
		frappe.throw(
			_("You do not have permission to run Cloud Sync."),
			frappe.PermissionError,
		)

	frappe.enqueue(
		"aci_workwear.aci_workwear.custom_script.sender.update_cloud_records",
		queue="long",
		timeout=20000,
		now=False,
	)

	return {
		"status": "queued",
		"message": "Push has been queued.",
	}