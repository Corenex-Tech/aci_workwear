# Copyright (c) 2026, Corenex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SyncUpConfiguration(Document):

	def validate(self):

		if self.sync_on_submit and self.document:

			meta = frappe.get_meta(self.document)

			if not meta.is_submittable:
				frappe.throw(
					_(
						"'{0}' is not a submittable DocType, so 'Sync on Submit' "
						"cannot be enabled for it."
					).format(self.document)
				)