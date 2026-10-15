# Copyright (c) 2025, Ashkar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_url_to_list


def execute(filters=None):
	filters = filters or {}
	company = filters.get("company")
	company_currency = (
		frappe.get_cached_value("Company", company, "default_currency")
		if company
		else None
	)
	columns = get_columns(company_currency)
	data = get_data(filters)
	return columns, data


def get_columns(currency=None):
	# The report is always shown in the company's own currency, so the
	# headings carry that currency rather than a hard-coded "SAR".
	currency_suffix = f" ({currency})" if currency else ""
	return [
		{
			"fieldname": "title",
			"label": _("Title"),
			"fieldtype": "Data",
			"width": 600,
		},
		{
			"fieldname": "amount",
			"label": _("Amount{0}").format(currency_suffix),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"fieldname": "adjustment_amount",
			"label": _("Adjustment{0}").format(currency_suffix),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"fieldname": "vat_amount",
			"label": _("VAT Amount{0}").format(currency_suffix),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Currency",
			"width": 150,
			"hidden": 1,
		},
	]


def get_data(filters):
	data = []

	# Validate if vat settings exist
	company = filters.get("company")
	if not company:
		frappe.throw(_("Company is required"))
	company_currency = frappe.get_cached_value("Company", company, "default_currency")

	if frappe.db.exists("KSA VAT Setting", company) is None:
		url = get_url_to_list("KSA VAT Setting")
		frappe.msgprint(_('Create <a href="{}">KSA VAT Setting</a> for this company').format(url))
		return data

	ksa_vat_setting = frappe.get_doc("KSA VAT Setting", company)

	# Sales Heading
	append_data(data, "VAT on Sales", "", "", "", company_currency)

	sales_grand_total_taxable_amount = 0
	sales_grand_total_taxable_adjustment_amount = 0
	sales_grand_total_tax = 0

	for vat_setting in ksa_vat_setting.ksa_vat_sales_accounts:
		(
			total_taxable_amount,
			total_taxable_adjustment_amount,
			total_tax,
		) = get_tax_data_for_each_vat_setting(vat_setting, filters, "Sales Invoice")

		append_data(
			data,
			vat_setting.title,
			total_taxable_amount,
			total_taxable_adjustment_amount,
			total_tax,
			company_currency,
		)

		sales_grand_total_taxable_amount += total_taxable_amount
		sales_grand_total_taxable_adjustment_amount += total_taxable_adjustment_amount
		sales_grand_total_tax += total_tax

	append_data(
		data,
		"Grand Total",
		sales_grand_total_taxable_amount,
		sales_grand_total_taxable_adjustment_amount,
		sales_grand_total_tax,
		company_currency,
	)

	append_data(data, "", "", "", "", company_currency)

	# Purchase Heading
	append_data(data, "VAT on Purchases", "", "", "", company_currency)

	purchase_grand_total_taxable_amount = 0
	purchase_grand_total_taxable_adjustment_amount = 0
	purchase_grand_total_tax = 0

	# Check if purchase accounts exist
	if not ksa_vat_setting.ksa_vat_purchase_accounts:
		append_data(
			data,
			"No Purchase VAT Settings Configured",
			0,
			0,
			0,
			company_currency,
		)
	else:
		for vat_setting in ksa_vat_setting.ksa_vat_purchase_accounts:
			(
				total_taxable_amount,
				total_taxable_adjustment_amount,
				total_tax,
			) = get_tax_data_for_each_vat_setting(vat_setting, filters, "Purchase Invoice")

			append_data(
				data,
				vat_setting.title,
				total_taxable_amount,
				total_taxable_adjustment_amount,
				total_tax,
				company_currency,
			)

			purchase_grand_total_taxable_amount += total_taxable_amount
			purchase_grand_total_taxable_adjustment_amount += total_taxable_adjustment_amount
			purchase_grand_total_tax += total_tax

	append_data(
		data,
		"Grand Total",
		purchase_grand_total_taxable_amount,
		purchase_grand_total_taxable_adjustment_amount,
		purchase_grand_total_tax,
		company_currency,
	)

	# Add Tax Payable Summary
	append_data(data, "", "", "", "", company_currency)
	append_data(data, "TAX PAYABLE SUMMARY", "", "", "", company_currency)
	append_data(data, "", "", "", "", company_currency)
	
	# Total Output VAT (Sales) - Bold title and amount
	append_data(
		data,
		"<b>Total Output VAT (Sales)</b>",
		"",
		"",
		sales_grand_total_tax,
		company_currency,
	)
	
	# Total Input VAT (Purchases) - Bold title and amount
	append_data(
		data,
		"<b>Total Input VAT (Purchases)</b>",
		"",
		"",
		purchase_grand_total_tax,
		company_currency,
	)
	
	# Net VAT Position
	net_vat = sales_grand_total_tax - purchase_grand_total_tax
	if net_vat > 0:
		status_text = "VAT Payable to Government"
		colorized_status = "<span style='color: red'><b>Status: You OWE tax to Saudi Government</b></span>"
	elif net_vat < 0:
		status_text = "VAT Refund from Government"
		colorized_status = "<span style='color: green'><b>Status: Saudi Government OWES you a refund</b></span>"
	else:
		status_text = "No VAT Payable/Refundable"
		colorized_status = "<span style='color: blue'><b>Status: No VAT payment required</b></span>"
	
	# Add the VAT amount row with bold amount - NO EMPTY ROW BEFORE
	append_data(
		data,
		f"<b>{status_text}</b>",
		"",
		"",
		abs(net_vat),
		company_currency,
	)
		
	# Add colorized status message at the BOTTOM - NO EMPTY ROW BEFORE
	append_data(
		data,
		colorized_status,
		"",
		"",
		"",
		company_currency,
	)

	return data


def get_tax_data_for_each_vat_setting(vat_setting, filters, doctype):
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	total_taxable_amount = 0
	total_taxable_adjustment_amount = 0
	total_tax = 0

	# Get company from filters for additional filtering
	company = filters.get("company")

	tax_doctype = (
		"Purchase Taxes and Charges"
		if doctype == "Purchase Invoice"
		else "Sales Taxes and Charges"
	)

	invoices = frappe.get_all(
		doctype,
		filters={
			"docstatus": 1,
			"posting_date": ["between", [from_date, to_date]],
			"company": company,
		},
		fields=["name", "is_return"],
	)

	for invoice in invoices:
		# An invoice may carry the VAT only in its taxes table, with no
		# item_tax_template on the items. Only then do untemplated items
		# belong to this VAT setting, and only when this account is on the
		# invoice. Items tagged with some OTHER template never belong here,
		# which is what stops the totals being over- and under-counted.
		invoice_has_tax_account = frappe.db.exists(
			tax_doctype,
			{
				"docstatus": 1,
				"parent": invoice.name,
				"account_head": vat_setting.account,
			},
		)

		invoice_items = frappe.get_all(
			f"{doctype} Item",
			filters={
				"docstatus": 1,
				"parent": invoice.name,
			},
			fields=["item_tax_template", "net_amount", "base_net_amount"],
		)

		invoice_items = [
			item
			for item in invoice_items
			if item.item_tax_template == vat_setting.item_tax_template
			or (not item.item_tax_template and invoice_has_tax_account)
		]

		if not invoice_items:
			continue  # Skip this invoice if no matching items

		for item in invoice_items:
			# base_net_amount is the company-currency amount. A real 0.00 is
			# still that amount, so test for None rather than truth, or a
			# zero base falls through to the foreign-currency net_amount.
			amount = item.base_net_amount
			if amount is None:
				amount = item.net_amount
			if amount is None:
				amount = 0

			if invoice.is_return == 0:
				total_taxable_amount += amount
			elif invoice.is_return == 1:
				total_taxable_adjustment_amount += amount

		# Add tax only if matching items exist
		total_tax += get_tax_amount(vat_setting.account, doctype, invoice.name)

	return total_taxable_amount, total_taxable_adjustment_amount, total_tax


def append_data(data, description, parent_account, tax_account, amount, company_currency, is_total_row=False):
	data.append({
		"title": description,
		"amount": parent_account,
		"adjustment_amount": tax_account,
		"vat_amount": amount,
		"currency": company_currency,
		"is_total_row": is_total_row
	})


def get_tax_amount(account_head, doctype, parent):
	if doctype == "Sales Invoice":
		tax_doctype = "Sales Taxes and Charges"
	elif doctype == "Purchase Invoice":
		tax_doctype = "Purchase Taxes and Charges"
	else:
		return 0

	# Get all tax entries for this invoice and account
	tax_entries = frappe.get_all(
		tax_doctype,
		filters={
			"docstatus": 1,
			"parent": parent,
			"account_head": account_head
		},
		fields=[
			"tax_amount",
			"base_tax_amount",
			"tax_amount_after_discount_amount",
			"base_tax_amount_after_discount_amount",
		]
	)

	total_tax_amount = 0
	for entry in tax_entries:
		# base_tax_amount holds the pre-discount tax; when an additional
		# discount is applied on Grand Total, the tax actually charged is
		# in *_after_discount_amount, which matches the invoice totals and GL.
		# base_* is the company-currency amount: a real 0.00 is still that
		# amount, so test for None rather than truth, or it falls through to
		# the foreign-currency figure.
		tax_amount = entry.base_tax_amount_after_discount_amount
		if tax_amount is None:
			tax_amount = entry.tax_amount_after_discount_amount
		if tax_amount is None:
			tax_amount = entry.base_tax_amount
		if tax_amount is None:
			tax_amount = entry.tax_amount
		if tax_amount is None:
			tax_amount = 0
		total_tax_amount += tax_amount

	return total_tax_amount
