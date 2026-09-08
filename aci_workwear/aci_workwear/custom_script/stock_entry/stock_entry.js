frappe.ui.form.on("Stock Entry", {
    custom_garment_work_orders: function(frm) {

        if (!frm.doc.custom_garment_work_orders) {
            frm.clear_table("items");
            frm.refresh_field("items");
            return;
        }

        frappe.call({
            method: "aci_workwear.aci_workwear.custom_script.stock_entry.stock_entry.get_garment_work_order_items",
            args: {
                work_order: frm.doc.custom_garment_work_orders
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

                // Clear existing Stock Entry items
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

                    // Custom links
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
                            frm.doc.custom_garment_work_orders
                        ]
                    ),
                    indicator: "green"
                });
            }
        });
    }
});