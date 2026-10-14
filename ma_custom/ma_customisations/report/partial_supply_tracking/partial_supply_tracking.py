# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import frappe
from erpnext import get_company_currency
from frappe import _

AMOUNT_FIELDS = ("invoiced_qty", "sales_amount", "purchase_amount", "profit")


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 180,
		},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Ordered"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Supplied"), "fieldname": "supplied_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Pending"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 100},
		{
			"label": _("Sales Invoice"),
			"fieldname": "sales_invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 170,
		},
		{"label": _("Invoiced Qty"), "fieldname": "invoiced_qty", "fieldtype": "Float", "width": 110},
		{
			"label": _("Purchase Invoice"),
			"fieldname": "purchase_invoice",
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"width": 170,
		},
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 170,
		},
		{
			"label": _("Sales Amt"),
			"fieldname": "sales_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Purchase Amt"),
			"fieldname": "purchase_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Profit"),
			"fieldname": "profit",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"label": _("Profit %"), "fieldname": "profit_percentage", "fieldtype": "Percent", "width": 100},
	]


def get_data(filters: frappe._dict) -> list[dict]:
	so_items = get_sales_order_items(filters)
	if not so_items:
		return []

	currency = get_company_currency(filters.company)
	invoice_rows = get_invoice_rows([d.so_detail for d in so_items], currency)

	data = []
	total = new_row(currency, sales_order=_("Total"), ordered_qty=0, supplied_qty=0, pending_qty=0)
	for so_item in so_items:
		summary = new_row(
			currency,
			sales_order=so_item.sales_order,
			item_code=so_item.item_code,
			ordered_qty=so_item.qty,
			supplied_qty=so_item.delivered_qty,
			pending_qty=so_item.qty - so_item.delivered_qty,
		)
		children = invoice_rows.get(so_item.so_detail, [])
		for child in children:
			add_amounts(summary, child)
		set_profit_percentage(summary)

		data.append(summary)
		data.extend(children)

		for field in ("ordered_qty", "supplied_qty", "pending_qty"):
			total[field] += summary[field]
		add_amounts(total, summary)

	set_profit_percentage(total)
	data.append(total)
	return data


def get_sales_order_items(filters: frappe._dict) -> list[frappe._dict]:
	so = frappe.qb.DocType("Sales Order")
	soi = frappe.qb.DocType("Sales Order Item")

	query = (
		frappe.qb.from_(soi)
		.join(so)
		.on(soi.parent == so.name)
		.select(
			so.name.as_("sales_order"),
			soi.name.as_("so_detail"),
			soi.item_code,
			soi.qty,
			soi.delivered_qty,
		)
		.where(so.docstatus == 1)
		.where(so.status != "Closed")
		.where(so.company == filters.company)
		.orderby(so.transaction_date)
		.orderby(so.name)
		.orderby(soi.idx)
	)

	if filters.customer:
		query = query.where(so.customer == filters.customer)
	if filters.sales_order:
		query = query.where(so.name == filters.sales_order)
	if filters.item_code:
		query = query.where(soi.item_code == filters.item_code)
	if filters.from_date:
		query = query.where(so.transaction_date >= filters.from_date)
	if filters.to_date:
		query = query.where(so.transaction_date <= filters.to_date)
	if filters.show_only_pending:
		query = query.where(soi.qty > soi.delivered_qty)

	return query.run(as_dict=True)


def get_invoice_rows(so_details: list[str], currency: str) -> dict[str, list[dict]]:
	sii = frappe.qb.DocType("Sales Invoice Item")
	si_items = (
		frappe.qb.from_(sii)
		.select(
			sii.so_detail,
			sii.parent.as_("sales_invoice"),
			sii.item_code,
			sii.qty,
			sii.stock_qty,
			sii.base_amount,
			sii.custom_purchase_invoice,
			sii.custom_purchase_invoice_item,
		)
		.where(sii.docstatus == 1)
		.where(sii.so_detail.isin(so_details))
		.orderby(sii.creation)
		.run(as_dict=True)
	)

	pi_items = get_purchase_invoice_items({d.custom_purchase_invoice for d in si_items} - {None, ""})

	rows = {}
	for d in si_items:
		pi_item = pi_items.get(d.custom_purchase_invoice_item) or pi_items.get(
			(d.custom_purchase_invoice, d.item_code)
		)
		purchase_amount = d.stock_qty * pi_item.base_rate / pi_item.conversion_factor if pi_item else 0
		row = new_row(
			currency,
			indent=1,
			sales_invoice=d.sales_invoice,
			invoiced_qty=d.qty,
			purchase_invoice=pi_item.parent if pi_item else None,
			purchase_order=pi_item.purchase_order if pi_item else None,
			sales_amount=d.base_amount,
			purchase_amount=purchase_amount,
			profit=d.base_amount - purchase_amount,
		)
		set_profit_percentage(row)
		rows.setdefault(d.so_detail, []).append(row)
	return rows


def get_purchase_invoice_items(purchase_invoices: set[str]) -> dict:
	if not purchase_invoices:
		return {}

	items = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", list(purchase_invoices)], "docstatus": 1},
		fields=["name", "parent", "item_code", "base_rate", "conversion_factor", "purchase_order"],
		order_by="idx",
	)
	by_key = {}
	for d in items:
		by_key[d.name] = d
		by_key.setdefault((d.parent, d.item_code), d)
	return by_key


def new_row(currency: str, indent: int = 0, **values) -> dict:
	return {"indent": indent, "currency": currency, **dict.fromkeys(AMOUNT_FIELDS, 0), **values}


def add_amounts(target: dict, source: dict):
	for field in AMOUNT_FIELDS:
		target[field] += source[field]


def set_profit_percentage(row: dict):
	row["profit_percentage"] = row["profit"] / row["sales_amount"] * 100 if row["sales_amount"] else 0
