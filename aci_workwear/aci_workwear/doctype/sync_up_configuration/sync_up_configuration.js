// Copyright (c) 2026, Corenex and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sync Up Configuration", {

	refresh(frm) {
		frm.trigger("document");
	},

	document(frm) {

		if (!frm.doc.document) {
			frm.set_df_property("sync_on_submit", "hidden", 1);
			frm.set_value("sync_on_submit", 0);
			return;
		}

		frappe.db.get_value("DocType", frm.doc.document, "is_submittable").then((r) => {

			const is_submittable = r.message && r.message.is_submittable;

			frm.set_df_property("sync_on_submit", "hidden", is_submittable ? 0 : 1);

			if (!is_submittable && frm.doc.sync_on_submit) {
				frm.set_value("sync_on_submit", 0);
			}
		});
	}
});