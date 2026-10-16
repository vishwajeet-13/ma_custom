# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import base64

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from ma_custom.ma_customisations.doctype.quotation_markup.quotation_markup import get_items_from_excel
from ma_custom.ma_customisations.report.invoice_wise_analytics.test_invoice_wise_analytics import (
	_default_company,
	_ensure_customer,
)

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Currency", "Customer", "Item", "Quotation", "UOM"]


def _ensure_item(code: str, item_name: str | None = None) -> str:
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": item_name or code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
	return code


class TestQuotationMarkup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _default_company()
		cls.customer = _ensure_customer("_QM Test Customer")
		cls.items = [_ensure_item(f"_QM Item {x}") for x in "ABC"]

	def _make_markup(self, rows=None):
		rows = rows or [
			(self.items[0], 10, 100, 10),
			(self.items[1], 5, 200, 10),
			(self.items[2], 20, 50, 15),
		]
		return frappe.get_doc(
			{
				"doctype": "Quotation Markup",
				"customer": self.customer,
				"company": self.company,
				"markup_percentage": 10,
				"items": [
					{"item_code": code, "qty": qty, "cost_rate": cost_rate, "markup_percentage": markup}
					for code, qty, cost_rate, markup in rows
				],
			}
		).insert()

	def test_spec_example(self):
		markup = self._make_markup()

		self.assertEqual([row.selling_rate for row in markup.items], [110, 220, 57.5])
		self.assertEqual([row.profit for row in markup.items], [100, 100, 150])
		self.assertEqual(markup.items[0].uom, "Nos")
		self.assertEqual(
			(markup.total_cost, markup.total_selling_amount, markup.total_markup), (3000, 3350, 350)
		)

		markup.submit()
		quotation = frappe.get_doc("Quotation", markup.quotation)
		self.assertEqual(quotation.docstatus, 0)
		self.assertEqual(quotation.party_name, self.customer)
		self.assertEqual(quotation.custom_quotation_markup, markup.name)
		self.assertEqual([row.rate for row in quotation.items], [110, 220, 57.5])
		self.assertEqual([row.price_list_rate for row in quotation.items], [110, 220, 57.5])
		self.assertEqual([row.discount_percentage for row in quotation.items], [0, 0, 0])
		self.assertEqual(quotation.grand_total, 3350)

	def test_profit_is_rounded(self):
		markup = self._make_markup([(self.items[0], 3, 0.1, 10)])
		self.assertEqual(markup.items[0].profit, 0.03)

	def test_totals_are_rounded(self):
		markup = self._make_markup([(self.items[0], 1, 0.1, 0), (self.items[1], 1, 0.2, 0)])
		self.assertEqual((markup.total_cost, markup.total_selling_amount), (0.3, 0.3))

	def test_submit_blocked_with_zero_qty(self):
		markup = self._make_markup([(self.items[0], 0, 100, 10)])
		self.assertRaisesRegex(frappe.ValidationError, "greater than 0 on row\\(s\\) 1", markup.submit)

	def test_excel_import_rejects_bad_numbers(self):
		xlsx = make_xlsx(
			[["Item Name", "Qty", "Cost Rate"], [self.items[0], "N/A", 100], [self.items[1], 2, 50]],
			"Sheet1",
		)
		self.assertRaisesRegex(
			frappe.ValidationError,
			"Excel row\\(s\\): 2$",
			get_items_from_excel,
			base64.b64encode(xlsx.getvalue()).decode(),
		)

	def test_submit_blocked_without_item(self):
		markup = self._make_markup([(self.items[0], 1, 100, 10), (None, 1, 100, 10)])
		self.assertRaisesRegex(frappe.ValidationError, "row\\(s\\) 2", markup.submit)

	def test_cancel_deletes_draft_quotation(self):
		markup = self._make_markup()
		markup.submit()
		quotation = markup.quotation

		markup.cancel()
		self.assertFalse(frappe.db.exists("Quotation", quotation))
		self.assertIsNone(markup.quotation)

	def test_cancel_blocked_when_quotation_submitted(self):
		markup = self._make_markup()
		markup.submit()
		frappe.get_doc("Quotation", markup.quotation).submit()

		self.assertRaisesRegex(frappe.ValidationError, "already submitted", markup.reload().cancel)

	def test_excel_import(self):
		by_name = _ensure_item("_QM-ITEM-D", "_QM Widget D")
		xlsx = make_xlsx(
			[
				["Customer enquiry"],
				["Item Name", "Notes", "Qty", "Cost Rate"],
				[self.items[0], "ignored", 10, 100],
				["_QM Widget D", "ignored", "5", "200.5"],
				["_QM Unknown", "ignored", 3, 7],
				[None, None, None, None],
			],
			"Sheet1",
		)
		items = get_items_from_excel(base64.b64encode(xlsx.getvalue()).decode())

		self.assertEqual(
			[(d["excel_item_name"], d["item_code"], d["uom"], d["qty"], d["cost_rate"]) for d in items],
			[
				(self.items[0], self.items[0], "Nos", 10, 100),
				("_QM Widget D", by_name, "Nos", 5, 200.5),
				("_QM Unknown", None, None, 3, 7),
			],
		)
