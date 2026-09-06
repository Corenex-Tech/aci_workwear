frappe.ui.form.on("Stock Entry", {
    custom_garment_work_order: function(frm) {
        if (!frm.doc.custom_garment_work_order) {
            return;
        }

        frappe.call({
            method: "aci_workwear.aci_workwear.custom_script.stock_entry.stock_entry.get_garment_work_order_items",
            args: {
                work_order: frm.doc.custom_garment_work_order
            },
            freeze: true,
            freeze_message: __("Fetching Garment Work Order items..."),

            callback: function(r) {
                if (!r.message) {
                    frappe.msgprint(
                        __("No items found in the selected Garment Work Order.")
                    );
                    return;
                }

                // Clear existing Stock Entry items
                frm.clear_table("items");

                r.message.forEach(function(wo_item) {
                    let row = frm.add_child("items");

                    row.item_code = wo_item.item_code;
                    row.item_name = wo_item.item_name;
                    row.qty = wo_item.qty;
                    row.uom = wo_item.uom;

                    // Optional:
                    // If you want stock UOM quantity to be same as qty
                    row.stock_qty = wo_item.qty;
                });

                frm.refresh_field("items");

                frappe.show_alert({
                    message: __(
                        "{0} item(s) added from Garment Work Order {1}",
                        [
                            r.message.length,
                            frm.doc.custom_garment_work_order
                        ]
                    ),
                    indicator: "green"
                });
            }
        });
    }
});