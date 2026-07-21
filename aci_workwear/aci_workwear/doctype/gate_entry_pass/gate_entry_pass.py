# Copyright (c) 2026, Corenex and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, nowtime


class GateEntryPass(Document):

	def validate(self):
		self.validate_items()
		if self.entry_type == "Inward":
			self.validate_return_against()

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Please add at least one item"))
	
		if self.gate_entry_purpose == "Non Inventory Movement":
			for row in self.items:
				if not row.get("non_inventory_item"):
					frappe.throw(_("Row {0}: Non Inventory Item is mandatory for Non Inventory Movement").format(row.idx))

	def validate_return_against(self):
		if not self.return_against and self.type == "Returnable":
			frappe.throw(_("Return Against (original Outward Gate Entry) is mandatory for Inward entries"))
		
		original = frappe.get_doc("Gate Entry Pass", self.return_against)

		if original.entry_type != "Outward":
			frappe.throw(_("Return Against must point to an Outward Gate Entry"))

		if original.docstatus != 1:
			frappe.throw(_("Return Against entry {0} is not submitted").format(self.return_against))

		if original.status == "Returned":
			frappe.throw(_("Referenced Gate Entry {0} is already fully returned").format(self.return_against))

	def on_submit(self):
		if self.gate_entry_purpose == "Inventory Movement":
			self.handle_sample_movement()
		elif self.gate_entry_purpose == "Non Inventory Movement":
			self.handle_customer_asset()

	def on_cancel(self):
		if self.stock_entry:
			se = frappe.get_doc("Stock Entry", self.stock_entry)
			if se.docstatus == 1:
				se.cancel()

		if self.entry_type == "Inward" and self.return_against:
			self.reverse_return_qty_on_original()

		self.status = "Cancelled"

	# ---------------- Inventory Movement (Stock impacting) ----------------

	def handle_sample_movement(self):
		if self.entry_type == "Outward":
			se_name = self.create_material_transfer(
				from_wh=self.source_warehouse,
				to_wh=self.target_warehouse,
				items=self.items,
			)
			self.db_set("stock_entry", se_name)
			self.db_set("status", "Out")

		elif self.entry_type == "Inward":
			self.validate_inward_qty_against_original()

			se_name = self.create_material_transfer(
				from_wh=self.target_warehouse,   
				to_wh=self.source_warehouse,      
				items=self.items,
			)
			self.db_set("stock_entry", se_name)
			self.db_set("status", "Returned")

			self.update_original_returned_qty()

	def create_material_transfer(self, from_wh, to_wh, items):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Transfer"
		se.purpose = "Material Transfer"
		se.custom_gate_entry_pass = self.name
		se.company = self.company
		se.posting_date = self.posting_date or nowdate()
		se.posting_time = self.posting_time or nowtime()
		se.set_posting_time = 1

		for row in items:
			se.append("items", {
				"item_code": row.item_code,
				"qty": row.qty,
				"uom": row.uom,
				"s_warehouse": row.source_warehouse or from_wh,
				"t_warehouse": row.target_warehouse or to_wh,
				"basic_rate": 0,  
			})

		se.insert(ignore_permissions=True)
		se.submit()
		return se.name

	def validate_inward_qty_against_original(self):
		original = frappe.get_doc("Gate Entry Pass", self.return_against)
		original_map = {row.item_code: row for row in original.items}

		for row in self.items:
			orig_row = original_map.get(row.item_code)
			if not orig_row:
				frappe.throw(_("Item {0} was not part of the original Outward entry {1}")
							.format(row.item_code, self.return_against))

			pending_qty = flt(orig_row.qty) - flt(orig_row.get("returned_qty") or 0)
			if flt(row.qty) > pending_qty:
				frappe.throw(_("Row {0}: Returned qty ({1}) exceeds pending qty ({2}) for item {3}")
							.format(row.idx, row.qty, pending_qty, row.item_code))

	def update_original_returned_qty(self):
		original = frappe.get_doc("Gate Entry Pass", self.return_against)
		inward_map = {row.item_code: flt(row.qty) for row in self.items}

		fully_returned = True
		for row in original.items:
			returned_now = inward_map.get(row.item_code, 0)
			row.returned_qty = flt(row.get("returned_qty") or 0) + returned_now
			if flt(row.returned_qty) < flt(row.qty):
				fully_returned = False

		original.status = "Returned" if fully_returned else "Partially Returned"
		original.flags.ignore_validate_update_after_submit = True
		original.save(ignore_permissions=True)
		

	def reverse_return_qty_on_original(self):
		original = frappe.get_doc("Gate Entry Pass", self.return_against)
		inward_map = {row.item_code: flt(row.qty) for row in self.items}

		for row in original.items:
			returned_now = inward_map.get(row.item_code, 0)
			row.returned_qty = flt(row.get("returned_qty") or 0) - returned_now

		original.status = "Out"
		original.flags.ignore_validate_update_after_submit = True
		original.save(ignore_permissions=True)

	# ---------------- Non Inventory Movement (No stock impact) ----------------

	def handle_customer_asset(self):
		if self.entry_type == "Outward":
			self.db_set("status", "Out")

		elif self.entry_type == "Inward":
			self.validate_serial_match_against_original()
			self.db_set("status", "Returned")
			self.update_original_asset_status()

	def validate_serial_match_against_original(self):
		original = frappe.get_doc("Gate Entry Pass", self.return_against)
		original_non_inventory_item = {row.non_inventory_item for row in original.items}

		for row in self.items:
			if row.non_inventory_item not in original_non_inventory_item:
				frappe.throw(_("Row {0}: Non Inventory Item {1} does not match any item in the original entry {2}")
							.format(row.idx, row.non_inventory_item, self.return_against))
			# if not row.get("condition_on_return"):
			# 	frappe.throw(_("Row {0}: Condition on Return is mandatory").format(row.idx))

	def update_original_asset_status(self):
		original = frappe.get_doc("Gate Entry Pass", self.return_against)
		returned_non_inventory_item = {row.non_inventory_item for row in self.items}
		original_non_inventory_item = {row.non_inventory_item for row in original.items}

		original.status = "Returned" if returned_non_inventory_item == original_non_inventory_item else "Partially Returned"
		original.flags.ignore_validate_update_after_submit = True
		original.save(ignore_permissions=True)


@frappe.whitelist()
def create_return_entry(source_name):
	source = frappe.get_doc("Gate Entry Pass", source_name)

	if source.entry_type != "Outward":
		frappe.throw(_("Only Outward entries can be returned."))

	if source.type != "Returnable":
		frappe.throw(_("Only Returnable entries can be returned."))

	doc = frappe.new_doc("Gate Entry Pass")

	# Parent fields
	doc.company = source.company
	doc.type = source.type
	doc.gate_entry_purpose = source.gate_entry_purpose
	doc.gate_entry_no = source.gate_entry_no
	doc.entry_type = "Inward"

	doc.source_warehouse = source.target_warehouse
	doc.target_warehouse = source.source_warehouse

	doc.return_against = source.name

	for d in source.items:
		doc.append("items", {
			"item_code": d.item_code,
			"non_inventory_item": d.non_inventory_item,
			"item_name": d.item_name,
			"qty": d.qty,
			"uom": d.uom,
			"non_inventory_item": d.non_inventory_item,
			"source_warehouse": d.target_warehouse,
			"target_warehouse": d.source_warehouse
		})

	doc.save()

	return doc.name