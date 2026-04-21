# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

# Avoid importing from `erpnext.*.test_*` modules: `erpnext.tests.utils` runs
# `BootStrapTestData()` at import time, which tries to insert `_Test Fiscal Year`
# records that overlap with fiscal years on any real site.
from ma_custom.ma_customisations.report.invoice_wise_analytics.invoice_wise_analytics import execute


def _default_company() -> str:
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {})
	if not company:
		raise RuntimeError("No Company exists on this site; cannot run report tests.")
	return company


def _first_account(company: str, account_type: str) -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": account_type, "is_group": 0},
		"name",
	)
	if not name:
		raise RuntimeError(f"No {account_type} account on {company}")
	return name


def _first_warehouse(company: str) -> str:
	name = frappe.db.get_value(
		"Warehouse",
		{"company": company, "is_group": 0, "disabled": 0},
		"name",
	)
	if not name:
		raise RuntimeError(f"No warehouse on {company}")
	return name


def _ensure_customer(name: str) -> str:
	if not frappe.db.exists("Customer", name):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
	return name


def _ensure_supplier(name: str) -> str:
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
	return name


def _ensure_item(code: str) -> str:
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,  # avoid needing stock ledger / valuation
			}
		).insert(ignore_permissions=True)
	return code


class TestInvoiceWiseAnalytics(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _default_company()
		cls.debit_to = _first_account(cls.company, "Receivable")
		cls.credit_to = _first_account(cls.company, "Payable")
		cls.income_account = frappe.db.get_value("Company", cls.company, "default_income_account") or _first_account(cls.company, "Income Account")
		cls.expense_account = frappe.db.get_value("Company", cls.company, "default_expense_account") or _first_account(cls.company, "Cost of Goods Sold")
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center") or frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name")
		cls.warehouse = _first_warehouse(cls.company)
		cls.customer = _ensure_customer("_IWA Test Customer")
		cls.customer2 = _ensure_customer("_IWA Test Customer 2")
		cls.supplier = _ensure_supplier("_IWA Test Supplier")
		cls.item = _ensure_item("_IWA Test Item")

	def _make_pi(self, qty=2, rate=50, posting_date=None):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": self.supplier,
				"posting_date": posting_date or nowdate(),
				"set_posting_time": 1,
				"credit_to": self.credit_to,
				"currency": "INR",
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"rate": rate,
						"expense_account": self.expense_account,
						"cost_center": self.cost_center,
						"warehouse": self.warehouse,
					}
				],
			}
		)
		pi.insert()
		pi.submit()
		return pi

	def _make_si(self, items, customer=None, posting_date=None):
		"""items: list of dicts with qty, rate, and optional pi/pi_item links."""
		si_items = []
		for it in items:
			row = {
				"item_code": self.item,
				"qty": it["qty"],
				"rate": it["rate"],
				"income_account": self.income_account,
				"cost_center": self.cost_center,
			}
			if it.get("pi_name"):
				row["custom_purchase_invoice"] = it["pi_name"]
			if it.get("pi_item_name"):
				row["custom_purchase_invoice_item"] = it["pi_item_name"]
			si_items.append(row)

		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer or self.customer,
				"posting_date": posting_date or nowdate(),
				"set_posting_time": 1,
				"debit_to": self.debit_to,
				"currency": "INR",
				"items": si_items,
			}
		)
		si.insert()
		si.submit()
		return si

	def _row_for(self, data, sales_invoice):
		rows = [row for row in data if row.get("sales_invoice") == sales_invoice]
		self.assertEqual(len(rows), 1, f"Expected exactly one row for {sales_invoice}, got {len(rows)}")
		return rows[0]

	def test_single_pi_linked_to_si(self):
		pi = self._make_pi(qty=2, rate=50)  # cost = 100
		si = self._make_si(
			[
				{
					"qty": 2,
					"rate": 100,
					"pi_name": pi.name,
					"pi_item_name": pi.items[0].name,
				}
			]
		)

		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate())
		)
		row = self._row_for(data, si.name)

		self.assertEqual(row.purchase_invoice_count, 1)
		self.assertEqual(row.purchase_invoice_total, 100.0)
		self.assertEqual(row.sales_invoice_total, si.grand_total)
		self.assertEqual(row.gross_profit, si.grand_total - 100.0)
		self.assertEqual(row.currency, si.currency)
		self.assertAlmostEqual(
			row.gross_profit_percentage,
			(si.grand_total - 100.0) / si.grand_total * 100,
		)

	def test_multiple_pis_linked_to_single_si(self):
		pi1 = self._make_pi(qty=1, rate=40)  # cost 40
		pi2 = self._make_pi(qty=3, rate=60)  # cost 180

		si = self._make_si(
			[
				{"qty": 1, "rate": 100, "pi_name": pi1.name, "pi_item_name": pi1.items[0].name},
				{"qty": 3, "rate": 100, "pi_name": pi2.name, "pi_item_name": pi2.items[0].name},
			]
		)

		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate())
		)
		row = self._row_for(data, si.name)

		self.assertEqual(row.purchase_invoice_count, 2)
		self.assertEqual(row.purchase_invoice_total, 40.0 + 180.0)
		self.assertEqual(row.gross_profit, si.grand_total - 220.0)

	def test_si_with_mixed_linked_and_standalone_items(self):
		pi = self._make_pi(qty=2, rate=50)  # cost = 100

		si = self._make_si(
			[
				{"qty": 2, "rate": 100, "pi_name": pi.name, "pi_item_name": pi.items[0].name},
				{"qty": 1, "rate": 500},  # standalone, must not contribute to PI total
			]
		)

		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate())
		)
		row = self._row_for(data, si.name)

		self.assertEqual(row.purchase_invoice_count, 1)
		self.assertEqual(row.purchase_invoice_total, 100.0)
		self.assertEqual(row.gross_profit, si.grand_total - 100.0)

	def test_standalone_si_has_zero_pi_cost(self):
		si = self._make_si([{"qty": 1, "rate": 100}])

		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate())
		)
		row = self._row_for(data, si.name)

		self.assertEqual(row.purchase_invoice_count, 0)
		self.assertEqual(row.purchase_invoice_total, 0.0)
		self.assertEqual(row.gross_profit, si.grand_total)
		self.assertEqual(row.gross_profit_percentage, 100.0)

	def test_date_and_customer_filters(self):
		pi_today = self._make_pi(qty=1, rate=30)
		si_today = self._make_si(
			[{"qty": 1, "rate": 100, "pi_name": pi_today.name, "pi_item_name": pi_today.items[0].name}]
		)
		pi_old = self._make_pi(qty=1, rate=30, posting_date=add_days(nowdate(), -10))
		si_old = self._make_si(
			[{"qty": 1, "rate": 100, "pi_name": pi_old.name, "pi_item_name": pi_old.items[0].name}],
			posting_date=add_days(nowdate(), -10),
		)
		si_other_cust = self._make_si([{"qty": 1, "rate": 100}], customer=self.customer2)

		# Date filter excludes old invoice
		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate())
		)
		invoices = {row["sales_invoice"] for row in data}
		self.assertIn(si_today.name, invoices)
		self.assertNotIn(si_old.name, invoices)

		# Customer filter limits to given customer
		_, data = execute(
			frappe._dict(
				company=self.company,
				from_date=add_days(nowdate(), -15),
				to_date=nowdate(),
				customer=self.customer2,
			)
		)
		invoices = {row["sales_invoice"] for row in data}
		self.assertIn(si_other_cust.name, invoices)
		self.assertNotIn(si_today.name, invoices)
		self.assertTrue(all(row["customer"] == self.customer2 for row in data))
