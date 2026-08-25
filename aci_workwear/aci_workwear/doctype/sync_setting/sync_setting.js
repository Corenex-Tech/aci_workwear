// Copyright (c) 2026, Corenex and contributors
// For license information, please see license.txt

// NOTE: this must live at
//   <app>/<module>/doctype/sync_setting/sync_setting.js
// It binds to the "Sync Setting" form.

frappe.ui.form.on("Sync Setting", {
	refresh(frm) {

		frm.add_custom_button(
			__("Push"),
			function () {

				frappe.confirm(
					__("This will push matching records to the cloud site. Continue?"),
					function () {

						frm.call({
							method:
								"aci_workwear.aci_workwear.doctype.sync_setting.sync_setting.enqueue_update_cloud_records",

							freeze: true,
							freeze_message: __("Queueing Push..."),

							callback: function (r) {

								if (r.exc) {
									return;
								}

								frappe.msgprint({
									title: __("Push"),
									message: __(
										"Push has been queued. It will run in the background - check Sync Log and the Error Log for results."
									),
									indicator: "green"
								});
							}
						});
					}
				);
			},
			__("Sync")
		);

	}
});