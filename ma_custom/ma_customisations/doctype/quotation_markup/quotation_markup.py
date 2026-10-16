# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import base64
from collections import Counter

import frappe
from erpnext import get_company_currency
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

EXCEL_COLUMNS = {"item name": "excel_item_name", "qty": "qty", "cost rate": "cost_rate"}


class QuotationMarkup(Document):
	def validate(self):
		self.currency = self.currency or get_company_currency(self.company)
		self.calculate_amounts()

	def calculate_amounts(self):
		for row in self.items:
			row.selling_rate = flt(
				flt(row.cost_rate) * (1 + flt(row.markup_percentage) / 100), row.precision("selling_rate")
			)
			row.cost_amount = flt(flt(row.qty) * flt(row.cost_rate), row.precision("cost_amount"))
			row.selling_amount = flt(flt(row.qty) * row.selling_rate, row.precision("selling_amount"))
			row.profit = flt(row.selling_amount - row.cost_amount, row.precision("profit"))

		self.total_cost = flt(sum(row.cost_amount for row in self.items), self.precision("total_cost"))
		self.total_selling_amount = flt(
			sum(row.selling_amount for row in self.items), self.precision("total_selling_amount")
		)
		self.total_markup = flt(self.total_selling_amount - self.total_cost, self.precision("total_markup"))

	def before_submit(self):
		if missing := [str(row.idx) for row in self.items if not row.item_code]:
			frappe.throw(_("Select an Item on row(s) {0} before submitting.").format(", ".join(missing)))
		if zero_qty := [str(row.idx) for row in self.items if flt(row.qty) <= 0]:
			frappe.throw(_("Qty must be greater than 0 on row(s) {0}.").format(", ".join(zero_qty)))

	def on_submit(self):
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": self.customer,
				"company": self.company,
				"transaction_date": self.transaction_date,
				"currency": self.currency,
				"ignore_pricing_rule": 1,
				"custom_quotation_markup": self.name,
				"items": [
					{
						"item_code": row.item_code,
						"qty": row.qty,
						"uom": row.uom,
						"price_list_rate": row.selling_rate,
						"rate": row.selling_rate,
					}
					for row in self.items
				],
			}
		).insert()
		self.db_set("quotation", quotation.name)

	def before_cancel(self):
		if self.get_quotation_docstatus() == 1:
			frappe.throw(
				_("Cannot cancel because Quotation {0} is already submitted.").format(
					frappe.bold(self.quotation)
				)
			)

	def on_cancel(self):
		if self.get_quotation_docstatus() == 0:
			quotation = self.quotation
			self.db_set("quotation", None)
			frappe.delete_doc("Quotation", quotation, ignore_permissions=True)

	def get_quotation_docstatus(self) -> int | None:
		return frappe.db.get_value("Quotation", self.quotation, "docstatus") if self.quotation else None


@frappe.whitelist()
def get_items_from_excel(file_content: str) -> list[dict]:
	frappe.has_permission("Quotation Markup", "create", throw=True)

	rows = read_xlsx_file_from_attached_file(fcontent=base64.b64decode(file_content.split(",", 1)[-1]))
	header_idx = next((i for i, row in enumerate(rows) if "item name" in normalise(row)), None)
	if header_idx is None:
		frappe.throw(_("Could not find an Item Name column in the Excel."))

	header = normalise(rows[header_idx])
	if missing := [label for label in EXCEL_COLUMNS if label not in header]:
		frappe.throw(_("Missing column(s) in the Excel: {0}").format(", ".join(missing)))
	index = {fieldname: header.index(label) for label, fieldname in EXCEL_COLUMNS.items()}

	items, invalid = [], []
	for excel_row, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
		item_name = str(row[index["excel_item_name"]] or "").strip()
		if item_name:
			qty, cost_rate = flt(row[index["qty"]]), flt(row[index["cost_rate"]])
			if qty <= 0 or cost_rate <= 0:
				invalid.append(str(excel_row))
			items.append({"excel_item_name": item_name, "qty": qty, "cost_rate": cost_rate})

	if invalid:
		frappe.throw(
			_("Qty and Cost Rate must be numbers greater than 0. Fix Excel row(s): {0}").format(
				", ".join(invalid)
			)
		)

	matches = match_items({d["excel_item_name"] for d in items})
	for d in items:
		d["item_code"], d["uom"] = matches.get(d["excel_item_name"].lower(), (None, None))
	return items


def normalise(row: list) -> list[str]:
	return [str(cell or "").strip().lower() for cell in row]


def match_items(names: set[str]) -> dict[str, tuple[str, str]]:
	filters = {"disabled": 0, "has_variants": 0}
	fields = ["name", "item_name", "stock_uom"]

	by_code = frappe.get_all("Item", filters={**filters, "name": ["in", list(names)]}, fields=fields)
	matches = {d.name.lower(): (d.name, d.stock_uom) for d in by_code}

	if remaining := [name for name in names if name.lower() not in matches]:
		by_name = frappe.get_all("Item", filters={**filters, "item_name": ["in", remaining]}, fields=fields)
		counts = Counter(d.item_name.lower() for d in by_name)
		for d in by_name:
			if counts[d.item_name.lower()] == 1:
				matches[d.item_name.lower()] = (d.name, d.stock_uom)
	return matches
