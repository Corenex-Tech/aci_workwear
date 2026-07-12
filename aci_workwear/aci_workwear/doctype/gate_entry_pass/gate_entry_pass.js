// Copyright (c) 2026, Corenex and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Entry Pass", {
	refresh(frm) {
        if (
            frm.doc.docstatus === 1 &&
            frm.doc.entry_type === "Outward" &&
            frm.doc.type === "Returnable" &&
            frm.doc.status !== "Returned"
        ) {
            frm.add_custom_button(__("Create Return Entry"), function () {
                frappe.call({
                    method: "aci_workwear.aci_workwear.doctype.gate_entry_pass.gate_entry_pass.create_return_entry",
                    args: {
                        source_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.set_route("Form", "Gate Entry Pass", r.message);
                        }
                    }
                });
            });
        }
	},
    gate_entry_purpose(frm) {
		toggle_child_fields(frm);
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
                    type: "Returnable",
                    entry_type: "Outward",
                    docstatus: 1,
                    name: ["!=", frm.doc.name],
                    gate_entry_purpose: frm.doc.gate_entry_purpose
                }
            };
        });
    }
});

frappe.ui.form.on("Gate Entry Items", {
    items_add(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        row.source_warehouse = frm.doc.source_warehouse;
        row.target_warehouse = frm.doc.target_warehouse;

        frm.refresh_field("items");
    }
});

function toggle_child_fields(frm) {
    let is_inventory = frm.doc.gate_entry_purpose === "Inventory Movement";
    let is_non_inventory = frm.doc.gate_entry_purpose === "Non Inventory Movement";

    // Mandatory fields
    frm.fields_dict.items.grid.update_docfield_property(
        "item_code",
        "reqd",
        is_inventory ? 1 : 0
    );

    frm.fields_dict.items.grid.update_docfield_property(
        "non_inventory_item",
        "reqd",
        is_inventory ? 0 : 1
    );

    // Read Only fields
    frm.fields_dict.items.grid.update_docfield_property(
        "item_code",
        "read_only",
        is_non_inventory ? 1 : 0
    );

    frm.fields_dict.items.grid.update_docfield_property(
        "item_name",
        "read_only",
        is_non_inventory ? 1 : 0
    );

    frm.refresh_field("items");
}

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