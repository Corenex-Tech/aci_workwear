from erpwork.erpwork.doctype.garment_work_order.garment_work_order import _get_required_item_row_names, _get_required_items_balance
from erpwork.overrides.stock_entry import _update_transferred_status
import frappe
from frappe import _, cint
from frappe.utils import flt


def update_material_receipt_before_submit(doc, method=None):
    """Update Garment Work Order before Material Receipt submit."""
    _update_material_receipt_on_stock_entry(
        doc,
        current_stock_entry=doc,
        publish_refresh=True,
    )

def update_material_receipt_on_submit(doc, method=None):
	"""Update Garment Work Order after Material Receipt submit."""
	_update_material_receipt_on_stock_entry(doc)


def update_material_receipt_on_cancel(doc, method=None):
	"""Recalculate Garment Work Order after Material Receipt cancellation."""
	_update_material_receipt_on_stock_entry(doc)
	

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


STOCK_ENTRY_TYPE_MATERIAL_RECEIPT = "Material Receipt"

def _sum_garment_receipt_qty_by_required_item(wo_name):
	"""Sum submitted Material Receipt quantities by Garment Work Order Required Item."""
	if not wo_name:
		return {}

	if not frappe.db.has_column(
		"Stock Entry Detail",
		"custom_garment_work_order"
	):
		return {}

	if not frappe.db.has_column(
		"Stock Entry Detail",
		"custom_garment_work_order_item"
	):
		return {}

	rows = frappe.db.sql("""
		SELECT
			sed.custom_garment_work_order_item AS req_item_name,
			SUM(sed.transfer_qty) AS total
		FROM `tabStock Entry Detail` sed
		INNER JOIN `tabStock Entry` se
			ON se.name = sed.parent
		INNER JOIN `tabGarment Work Order Required Item` ri
			ON ri.name = sed.custom_garment_work_order_item
			AND ri.parent = %s
			AND ri.item_code = sed.item_code
		WHERE sed.custom_garment_work_order = %s
			AND se.docstatus = 1
			AND se.stock_entry_type = %s
			AND sed.item_code IS NOT NULL
			AND sed.item_code != ''
			AND sed.custom_garment_work_order_item IS NOT NULL
			AND sed.custom_garment_work_order_item != ''
		GROUP BY sed.custom_garment_work_order_item
	""", (
		wo_name,
		wo_name,
		STOCK_ENTRY_TYPE_MATERIAL_RECEIPT,
	), as_dict=True)

	return {
		row.req_item_name: flt(row.total)
		for row in rows
		if row.req_item_name
	}


def _add_draft_garment_receipt_qty(
	received_by_row,
	wo_name,
	current_stock_entry,
):
	"""Include current draft Material Receipt quantities."""
	if not current_stock_entry:
		return

	if not getattr(current_stock_entry, "items", None):
		return

	if cint(getattr(current_stock_entry, "docstatus", 0)) != 0:
		return

	req_item_codes = {
		row.name: row.item_code
		for row in frappe.get_all(
			"Garment Work Order Required Item",
			filters={"parent": wo_name},
			fields=["name", "item_code"],
		)
		if row.name and row.item_code
	}

	for item in current_stock_entry.items:
		item_wo = (
			getattr(
				item,
				"custom_garment_work_order",
				None
			)
			or ""
		).strip()

		if item_wo != wo_name:
			continue

		req_item_name = (
			getattr(
				item,
				"custom_garment_work_order_item",
				None
			)
			or ""
		).strip()

		item_code = (
			getattr(item, "item_code", None)
			or ""
		).strip()

		if not req_item_name or not item_code:
			continue

		if req_item_codes.get(req_item_name) != item_code:
			continue

		qty = flt(item.transfer_qty)

		if qty:
			received_by_row[req_item_name] = (
				received_by_row.get(req_item_name, 0) + qty
			)


def _update_required_items_received_qty(
	wo_name,
	current_stock_entry=None,
	required_item_names=None,
):
	"""Update transferred_qty on Garment Work Order Required Item."""
	if not wo_name:
		return

	if not frappe.db.has_column(
		"Garment Work Order Required Item",
		"transferred_qty"
	):
		return

	received_by_row = _sum_garment_receipt_qty_by_required_item(
		wo_name
	)

	_add_draft_garment_receipt_qty(
		received_by_row,
		wo_name,
		current_stock_entry,
	)

	filters = {
		"parent": wo_name
	}

	if required_item_names is not None:
		if not required_item_names:
			return

		filters["name"] = [
			"in",
			list(required_item_names)
		]

	rows = frappe.get_all(
		"Garment Work Order Required Item",
		filters=filters,
		fields=["name"],
	)

	for row in rows:
		transferred_qty = flt(
			received_by_row.get(row.name, 0)
		)

		frappe.db.set_value(
			"Garment Work Order Required Item",
			row.name,
			"transferred_qty",
			transferred_qty,
			update_modified=False,
		)


def _get_material_status(wo_name):
	"""Return Material Receipt status for Garment Work Order."""
	if not wo_name:
		return "No Receipt"

	if not frappe.db.has_column(
		"Garment Work Order Required Item",
		"transferred_qty"
	):
		return "No Receipt"

	result = frappe.db.sql("""
		SELECT
			COALESCE(SUM(mr_qty), 0) AS total_required,
			COALESCE(SUM(transferred_qty), 0) AS total_received
		FROM `tabGarment Work Order Required Item`
		WHERE parent = %s
	""", (wo_name,), as_dict=True)

	if not result:
		return "No Receipt"

	total_required = flt(result[0].total_required)
	total_received = flt(result[0].total_received)

	if total_required <= 0:
		return "No Receipt"

	if total_received >= total_required:
		return "Material Received"

	if total_received > 0:
		return "Material Received Partial"

	return "No Receipt"


def _update_material_status(wo_name, publish_refresh=False):
	"""Update Material Receipt status on Garment Work Order."""
	if not wo_name:
		return

	if not frappe.db.has_column(
		"Garment Work Order",
		"material_status"
	):
		return

	material_status = _get_material_status(wo_name)

	frappe.db.set_value(
		"Garment Work Order",
		wo_name,
		"material_status",
		material_status,
		update_modified=publish_refresh,
	)

	if publish_refresh:
		modified = frappe.db.get_value(
			"Garment Work Order",
			wo_name,
			"modified",
		)

		frappe.publish_realtime(
			"doc_update",
			{
				"modified": str(modified),
				"doctype": "Garment Work Order",
				"name": wo_name,
			},
			doctype="Garment Work Order",
			docname=wo_name,
		)


def _update_material_receipt_on_stock_entry(
    doc,
    current_stock_entry=None,
    publish_refresh=False,
):
    if doc.company != "ACI Exports Private Limited":
        return
    
    """Update Garment Work Order from Material Receipt."""
    if doc.stock_entry_type != STOCK_ENTRY_TYPE_MATERIAL_RECEIPT:
        return

    if not doc.items:
        return

    required_items_by_work_order = {}

    for item in doc.items:
        wo_name = (
            getattr(
                item,
                "custom_garment_work_order",
                None
            )
            or ""
        ).strip()

        req_item_name = (
            getattr(
                item,
                "custom_garment_work_order_item",
                None
            )
            or ""
        ).strip()

        item_code = (
            getattr(item, "item_code", None)
            or ""
        ).strip()

        if not wo_name or not req_item_name or not item_code:
            continue

        req_item = frappe.db.get_value(
            "Garment Work Order Required Item",
            req_item_name,
            ["parent", "item_code"],
            as_dict=True,
        )

        if not req_item:
            continue

        if req_item.parent != wo_name:
            continue

        if req_item.item_code != item_code:
            continue

        required_items_by_work_order.setdefault(
            wo_name,
            set(),
        ).add(req_item_name)

    for wo_name, required_item_names in required_items_by_work_order.items():
        _update_required_items_received_qty(
            wo_name,
            current_stock_entry=current_stock_entry,
            required_item_names=required_item_names,
        )

        _update_material_status(
            wo_name,
            publish_refresh=publish_refresh,
        )
