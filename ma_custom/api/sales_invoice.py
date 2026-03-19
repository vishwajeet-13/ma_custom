import json

import frappe
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc


@frappe.whitelist()
def make_sales_invoice_from_purchase_invoice(
	source_name: str,
	target_doc: str | Document | None = None,
	args: str | dict | None = None,
):
	if args and isinstance(args, str):
		args = json.loads(args)
	args = args or {}

	def set_missing_values(source, target):
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		return d.name in filtered_items if filtered_items else True

	doclist = get_mapped_doc(
		"Purchase Invoice",
		source_name,
		{
			"Purchase Invoice": {
				"doctype": "Sales Invoice",
				"validation": {"docstatus": ["=", 1]},
			},
			"Purchase Invoice Item": {
				"doctype": "Sales Invoice Item",
				"field_map": {
					"name": "custom_purchase_invoice_item",
					"parent": "custom_purchase_invoice",
				},
				"field_no_map": [
					"expense_account",
					"warehouse",
					"cost_center",
				],
				"condition": select_item,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist
