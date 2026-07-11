// Copyright (c) 2026, Corenex and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Entry Pass", {
	refresh(frm) {

	},
    source_warehouse(frm) {
        set_warehouse_in_children(frm, "items", "source_warehouse", frm.doc.source_warehouse);
    },
    target_warehouse(frm) {
        set_warehouse_in_children(frm, "items", "target_warehouse", frm.doc.target_warehouse);
    },
    setup: function(frm) {
        frm.set_query("return_against", function() {
            return {
                filters: {
                    status: ["!=", "Returned"],
                    entry_type: "Outward",
                    docstatus: 1,
                    name: ["!=", frm.doc.name],
                    gate_entry_purpose: frm.doc.gate_entry_purpose
                }
            };
        });
    }
});


function set_warehouse_in_children(frm, child_table, warehouse_field, warehouse) {
    frm.doc[child_table].forEach((row) => {
        frappe.model.set_value(
            row.doctype,
            row.name,
            warehouse_field,
            warehouse
        );
    });
}