import frappe


@frappe.whitelist()
def get_garment_work_order_items(work_order):
    if not work_order:
        return []

    wo = frappe.get_doc("Garment Work Order", work_order)

    if wo.docstatus == 2:
        frappe.throw(f"Garment Work Order {work_order} is cancelled.")

    items = []

    for row in wo.items:
        if not row.item_code:
            continue

        items.append({
            "item_code": row.item_code,
            "item_name": row.item_name,
            "qty": row.wo_qty or 0,
            "uom": frappe.db.get_value(
                "Item",
                row.item_code,
                "stock_uom"
            ),
        })

    return items
