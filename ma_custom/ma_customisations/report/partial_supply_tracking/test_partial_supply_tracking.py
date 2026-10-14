# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from ma_custom.ma_customisations.report.invoice_wise_analytics.test_invoice_wise_analytics import (
	_default_company,
	_ensure_customer,
	_ensure_supplier,
	_first_warehouse,
)
from ma_custom.ma_customisations.report.partial_supply_tracking.partial_supply_tracking import execute


def _ensure_stock_item(code: str) -> str:
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
	return code


class TestPartialSupplyTracking(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _default_company()
		cls.warehouse = _first_warehouse(cls.company)
		cls.customer = _ensure_customer("_PST Test Customer")
		cls.supplier = _ensure_supplier("_PST Test Supplier")

	def _make_pi(self, item_code, qty, rate):
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": self.supplier,
				"schedule_date": nowdate(),
				"items": [{"item_code": item_code, "qty": qty, "rate": rate, "warehouse": self.warehouse}],
			}
		).submit()
		return frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": self.supplier,
				"update_stock": 1,
				"items": [
					{
						"item_code": item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"purchase_order": po.name,
						"po_detail": po.items[0].name,
					}
				],
			}
		).submit()

	def _make_so(self, items, transaction_date=None):
		return frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer,
				"transaction_date": transaction_date or nowdate(),
				"delivery_date": nowdate(),
				"items": [
					{"item_code": code, "qty": qty, "rate": rate, "warehouse": self.warehouse}
					for code, qty, rate in items
				],
			}
		).submit()

	def _so_row(self, so, item_code):
		return next(d for d in so.items if d.item_code == item_code)

	def _deliver(self, so, item_code, qty):
		so_row = self._so_row(so, item_code)
		return frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": self.company,
				"customer": self.customer,
				"items": [
					{
						"item_code": item_code,
						"qty": qty,
						"rate": so_row.rate,
						"warehouse": self.warehouse,
						"against_sales_order": so.name,
						"so_detail": so_row.name,
					}
				],
			}
		).submit()

	def _invoice(self, so, item_code, qty, pi=None, update_stock=0, link_pi_item=True):
		so_row = self._so_row(so, item_code)
		row = {
			"item_code": item_code,
			"qty": qty,
			"rate": so_row.rate,
			"uom": so_row.uom,
			"conversion_factor": so_row.conversion_factor,
			"warehouse": self.warehouse,
			"sales_order": so.name,
			"so_detail": so_row.name,
		}
		if pi:
			row["custom_purchase_invoice"] = pi.name
			if link_pi_item:
				row["custom_purchase_invoice_item"] = pi.items[0].name
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"update_stock": update_stock,
				"items": [row],
			}
		).submit()

	def _run(self, **filters):
		_, data = execute(
			frappe._dict(company=self.company, from_date=nowdate(), to_date=nowdate(), **filters)
		)
		return data

	def _summary(self, data, so, item_code):
		return next(
			d
			for d in data
			if d["indent"] == 0 and d["sales_order"] == so.name and d.get("item_code") == item_code
		)

	def _children(self, data, summary):
		start = data.index(summary) + 1
		children = []
		for d in data[start:]:
			if d["indent"] == 0:
				break
			children.append(d)
		return children

	def test_spec_scenarios(self):
		a, b, c, d, e = (_ensure_stock_item(f"_PST Item {x}") for x in "ABCDE")
		pi_a1, pi_a2 = self._make_pi(a, 60, 44), self._make_pi(a, 40, 46)
		pi_b1, pi_b2 = self._make_pi(b, 30, 21), self._make_pi(b, 20, 22)
		pi_d = self._make_pi(d, 50, 34)
		self._make_pi(e, 25, 10)

		so1 = self._make_so([(a, 100, 50), (b, 80, 25), (c, 20, 10)])
		si_a1 = self._invoice(so1, a, 60, pi_a1, update_stock=1)
		self._invoice(so1, a, 40, pi_a2, update_stock=1)
		self._invoice(so1, b, 30, pi_b1, update_stock=1)
		self._invoice(so1, b, 20, pi_b2, update_stock=1, link_pi_item=False)

		so2 = self._make_so([(d, 50, 40), (e, 40, 10)])
		self._deliver(so2, d, 30)
		self._deliver(so2, d, 20)
		self._invoice(so2, d, 50, pi_d)
		self._deliver(so2, e, 25)

		data = self._run()

		row_a = self._summary(data, so1, a)
		self.assertEqual((row_a["ordered_qty"], row_a["supplied_qty"], row_a["pending_qty"]), (100, 100, 0))
		self.assertEqual((row_a["invoiced_qty"], row_a["sales_amount"]), (100, 5000))
		self.assertEqual((row_a["purchase_amount"], row_a["profit"]), (4480, 520))
		self.assertAlmostEqual(row_a["profit_percentage"], 10.4)
		children_a = self._children(data, row_a)
		self.assertEqual(len(children_a), 2)
		self.assertEqual(children_a[0]["sales_invoice"], si_a1.name)
		self.assertEqual(children_a[0]["purchase_invoice"], pi_a1.name)
		self.assertEqual(children_a[0]["purchase_order"], pi_a1.items[0].purchase_order)
		self.assertEqual((children_a[0]["purchase_amount"], children_a[0]["profit"]), (2640, 360))

		row_b = self._summary(data, so1, b)
		self.assertEqual((row_b["supplied_qty"], row_b["pending_qty"]), (50, 30))
		self.assertEqual(
			(row_b["sales_amount"], row_b["purchase_amount"], row_b["profit"]), (1250, 1070, 180)
		)

		row_c = self._summary(data, so1, c)
		self.assertEqual((row_c["supplied_qty"], row_c["pending_qty"], row_c["sales_amount"]), (0, 20, 0))
		self.assertEqual(self._children(data, row_c), [])

		row_d = self._summary(data, so2, d)
		self.assertEqual((row_d["supplied_qty"], row_d["pending_qty"], row_d["invoiced_qty"]), (50, 0, 50))
		self.assertEqual(
			(row_d["sales_amount"], row_d["purchase_amount"], row_d["profit"]), (2000, 1700, 300)
		)
		self.assertEqual(len(self._children(data, row_d)), 1)

		row_e = self._summary(data, so2, e)
		self.assertEqual((row_e["supplied_qty"], row_e["pending_qty"], row_e["profit"]), (25, 15, 0))
		self.assertEqual(self._children(data, row_e), [])

		pending = self._run(show_only_pending=1)
		pending_items = {(r["sales_order"], r.get("item_code")) for r in pending if r["indent"] == 0}
		self.assertNotIn((so1.name, a), pending_items)
		self.assertIn((so1.name, b), pending_items)
		self.assertIn((so2.name, e), pending_items)

		scoped = self._run(sales_order=so2.name)
		self.assertEqual(scoped[-1]["sales_order"], "Total")
		self.assertEqual((scoped[-1]["ordered_qty"], scoped[-1]["supplied_qty"]), (90, 75))
		self.assertEqual((scoped[-1]["sales_amount"], scoped[-1]["profit"]), (2000, 300))

	def test_mixed_delivery_and_cancelled_invoice(self):
		f = _ensure_stock_item("_PST Item F")
		pi_f = self._make_pi(f, 30, 60)
		so = self._make_so([(f, 60, 70)])
		self._deliver(so, f, 20)
		self._invoice(so, f, 10, pi_f, update_stock=1)
		cancelled = self._invoice(so, f, 5, pi_f)
		cancelled.reload()
		cancelled.cancel()

		data = self._run(sales_order=so.name)
		row = self._summary(data, so, f)
		self.assertEqual((row["supplied_qty"], row["pending_qty"], row["invoiced_qty"]), (30, 30, 10))
		self.assertEqual((row["sales_amount"], row["purchase_amount"], row["profit"]), (700, 600, 100))
		self.assertEqual(len(self._children(data, row)), 1)

	def test_date_filter_uses_sales_order_date(self):
		item = _ensure_stock_item("_PST Item G")
		old_so = self._make_so([(item, 5, 10)], transaction_date=add_days(nowdate(), -10))
		self.assertFalse([r for r in self._run() if r.get("sales_order") == old_so.name])

	def test_closed_sales_order_is_hidden(self):
		item = _ensure_stock_item("_PST Item H")
		so = self._make_so([(item, 5, 10)])
		so.update_status("Closed")
		self.assertFalse([r for r in self._run() if r.get("sales_order") == so.name])

	def test_purchase_amount_uses_stock_uom(self):
		item = _ensure_stock_item("_PST Item Box")
		pi = self._make_pi(item, 20, 5)
		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer,
				"delivery_date": nowdate(),
				"items": [
					{
						"item_code": item,
						"qty": 2,
						"uom": "Box",
						"conversion_factor": 10,
						"rate": 80,
						"warehouse": self.warehouse,
					}
				],
			}
		).submit()
		self._invoice(so, item, 2, pi, update_stock=1)

		row = self._summary(self._run(sales_order=so.name), so, item)
		self.assertEqual((row["invoiced_qty"], row["sales_amount"]), (2, 160))
		self.assertEqual((row["purchase_amount"], row["profit"]), (100, 60))
