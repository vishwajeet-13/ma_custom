// Copyright (c) 2026, BWH and contributors
// For license information, please see license.txt

frappe.query_reports["Partial Supply Tracking"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "sales_order",
			label: __("Sales Order"),
			fieldtype: "Link",
			options: "Sales Order",
		},
		{
			fieldname: "item_code",
			label: __("Item Code"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "show_only_pending",
			label: __("Show Only Pending"),
			fieldtype: "Check",
		},
	],
	tree: true,
	initial_depth: 1,
	formatter(value, row, column, data, default_formatter) {
		if (data && column.fieldname === "sales_order" && data.indent === 0 && !data.item_code) {
			return `<b>${data.sales_order}</b>`;
		}
		if (
			data &&
			data.indent === 1 &&
			["ordered_qty", "supplied_qty", "pending_qty"].includes(column.fieldname)
		) {
			return "";
		}
		value = default_formatter(value, row, column, data);
		if (data && data.indent === 0) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
