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

        set_warehouse_filter(frm);

	},
    entry_type(frm) {
        set_warehouse_filter(frm);
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
    type: function(frm){
        if (frm.doc.type == "Work Order – Issue"){
            frm.set_value("entry_type", "Outward")
            frm.set_value("status", "Draft")
        }else if(frm.doc.type == "Work Order – Receive"){
            frm.set_value("entry_type", "Inward")
            frm.set_value("status", "Draft")
        }
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
    },
    garment_work_order: function(frm) {

        if (!frm.doc.garment_work_order) {
            frm.clear_table("items");
            frm.refresh_field("items");
            return;
        }

        frappe.call({
            method: "aci_workwear.aci_workwear.custom_script.stock_entry.stock_entry.get_garment_work_order_items",
            args: {
                work_order: frm.doc.garment_work_order
            },
            freeze: true,
            freeze_message: __("Fetching Garment Work Order items..."),

            callback: function(r) {

                if (!r.message || !r.message.length) {
                    frm.clear_table("items");
                    frm.refresh_field("items");

                    frappe.msgprint(
                        __("No available items found for the selected Garment Work Order.")
                    );

                    return;
                }

                frm.clear_table("items");

                r.message.forEach(function(wo_item) {

                    let row = frm.add_child("items");

                    // Item details
                    row.item_code = wo_item.item_code;
                    row.item_name = wo_item.item_name;

                    // Quantity/UOM
                    row.qty = wo_item.qty;
                    row.uom = wo_item.uom;
                    row.stock_uom = wo_item.stock_uom;
                    row.conversion_factor = wo_item.conversion_factor;
                    row.transfer_qty = wo_item.transfer_qty;

                    // Warehouses
                    row.s_warehouse = wo_item.s_warehouse;
                    row.t_warehouse = wo_item.t_warehouse;

                    row.custom_garment_work_order =
                        wo_item.custom_garment_work_order;

                    row.custom_garment_work_order_item =
                        wo_item.custom_garment_work_order_item;

                    row.custom_garment_planning =
                        wo_item.custom_garment_planning;
                });

                frm.refresh_field("items");

                frappe.show_alert({
                    message: __(
                        "{0} item(s) added from Garment Work Order {1}",
                        [
                            r.message.length,
                            frm.doc.garment_work_order
                        ]
                    ),
                    indicator: "green"
                });
            }
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


function set_warehouse_filter(frm) {

    frm.set_query("target_warehouse", function () {
        if (frm.doc.entry_type === "Outward") {
            return {
                filters: {
                    custom_is_gate_entry_warehouse: 1
                }
            };
        }
    });

    frm.set_query("source_warehouse", function () {
        if (frm.doc.entry_type === "Inward") {
            return {
                filters: {
                    custom_is_gate_entry_warehouse: 1
                }
            };
        }
    });
}