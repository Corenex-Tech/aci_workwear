from erpwork.erpwork.doctype.garment_work_order.garment_work_order import _get_required_item_row_names, _get_required_items_balance
import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_garment_work_order_items(work_order):
    """
    This uses:
        - Garment Work Order required_items
        - Material Request deduction logic
        - Transferred quantity balance
        - Required item UOM
        - Item stock UOM
        - UOM conversion factor
    """

    if not work_order:
        return []

    wo = frappe.get_doc("Garment Work Order", work_order)

    if wo.docstatus == 2:
        frappe.throw(
            _("Garment Work Order {0} is cancelled.").format(work_order)
        )

    if wo.docstatus != 1:
        frappe.throw(
            _("Garment Work Order must be submitted before fetching items.")
        )

    # Same calculation used by create_material_transfer_stock_entry()
    wo.update_required_items()

    if not wo.required_items:
        return []

    # Same MR deduction logic as material transfer
    deduct_mr = not bool(
        getattr(wo, "skip_material_transfer_request", 0)
    )

    balance_map = _get_required_items_balance(
        wo,
        deduct_material_request_qty=deduct_mr
    )

    if not balance_map:
        return []

    req_row_names = _get_required_item_row_names(work_order)

    items = []

    for item_code, b in balance_map.items():

        if not item_code:
            continue

        item_uom = (
            b.get("uom")
            or frappe.db.get_value(
                "Item",
                item_code,
                "stock_uom"
            )
        )

        stock_uom = frappe.db.get_value(
            "Item",
            item_code,
            "stock_uom"
        )

        conversion_factor = flt(
            frappe.db.get_value(
                "UOM Conversion Detail",
                {
                    "parent": item_code,
                    "uom": item_uom,
                },
                "conversion_factor",
            )
        ) or 1

        balance_qty = flt(b.get("qty"))

        transfer_qty = balance_qty * conversion_factor

        items.append({
            "item_code": b.get("item_code") or item_code,
            "item_name": b.get("item_name"),
            "qty": balance_qty,
            "uom": item_uom,
            "stock_uom": stock_uom,
            "conversion_factor": conversion_factor,
            "transfer_qty": transfer_qty,

            "custom_garment_work_order": work_order,
            "custom_garment_work_order_item": (
                b.get("required_item_name")
                or req_row_names.get(item_code)
            ),
            "custom_garment_planning": wo.garment_planning,

            "s_warehouse": wo.set_source_warehouse,
            "t_warehouse": wo.set_target_warehouse,
        })

    return items