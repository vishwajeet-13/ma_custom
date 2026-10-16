# Copyright (c) 2026, BWH and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Count, Sum


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns() -> list[dict]:
	return [
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 200,
		},
		{
			"label": _("Sales Invoice"),
			"fieldname": "sales_invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 180,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		},
		{
			"label": _("Purchase Invoices"),
			"fieldname": "purchase_invoice_count",
			"fieldtype": "Int",
			"width": 140,
		},
		{
			"label": _("Purchase Invoice Total"),
			"fieldname": "purchase_invoice_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 180,
		},
		{
			"label": _("Sales Invoice Total"),
			"fieldname": "sales_invoice_total",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 170,
		},
		{
			"label": _("Gross Profit"),
			"fieldname": "gross_profit",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("Gross Profit %"),
			"fieldname": "gross_profit_percentage",
			"fieldtype": "Percent",
			"width": 140,
		},
	]


def get_data(filters: frappe._dict) -> list[dict]:
	si = frappe.qb.DocType("Sales Invoice")
	sii = frappe.qb.DocType("Sales Invoice Item")
	pii = frappe.qb.DocType("Purchase Invoice Item")

	# Subquery: per Sales Invoice, count distinct PIs and sum cost from the linked PI items
	pi_stats = (
		frappe.qb.from_(sii)
		.left_join(pii)
		.on(sii.custom_purchase_invoice_item == pii.name)
		.select(
			sii.parent.as_("sales_invoice"),
			Count(sii.custom_purchase_invoice).distinct().as_("pi_count"),
			Sum(pii.net_amount).as_("pi_total"),
		)
		.where(sii.docstatus == 1)
		.where(sii.custom_purchase_invoice.isnotnull())
		.where(sii.custom_purchase_invoice != "")
		.groupby(sii.parent)
	)

	query = (
		frappe.qb.from_(si)
		.left_join(pi_stats)
		.on(si.name == pi_stats.sales_invoice)
		.select(
			si.customer,
			si.name.as_("sales_invoice"),
			si.currency,
			Coalesce(pi_stats.pi_count, 0).as_("purchase_invoice_count"),
			Coalesce(pi_stats.pi_total, 0).as_("purchase_invoice_total"),
			si.grand_total.as_("sales_invoice_total"),
			(si.grand_total - Coalesce(pi_stats.pi_total, 0)).as_("gross_profit"),
		)
		.where(si.docstatus == 1)
		.where(si.company == filters.company)
		.orderby(si.customer)
		.orderby(si.posting_date)
	)

	if filters.customer:
		query = query.where(si.customer == filters.customer)
	if filters.from_date:
		query = query.where(si.posting_date >= filters.from_date)
	if filters.to_date:
		query = query.where(si.posting_date <= filters.to_date)

	rows = query.run(as_dict=True)
	for row in rows:
		sales_total = row["sales_invoice_total"] or 0
		row["gross_profit_percentage"] = (row["gross_profit"] / sales_total * 100) if sales_total else 0
	return rows
