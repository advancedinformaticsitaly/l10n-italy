# -*- coding: utf-8 -*-


from openerp import fields, models, _
from openerp.exceptions import ValidationError, Warning as UserError


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    comunicazione_dati_iva_escludi = fields.Boolean(
        string='Exclude from invoices communication')

    def _compute_taxes_in_company_currency(self, vals):
        sign = 1 if self.type in ('out_invoice', 'in_refund') else -1
        amount_total_signed = sign * self.amount_total
        currency_id = self.currency_id.with_context(date=self.date_invoice)
        amount_total_company = currency_id.compute(
            self.amount_total, self.company_id.currency_id)
        amount_total_company_signed = sign * amount_total_company
        try:
            exchange_rate = (
                amount_total_signed /
                amount_total_company_signed)
        except ZeroDivisionError:
            exchange_rate = 1
        vals['ImponibileImporto'] = vals['ImponibileImporto'] / exchange_rate
        vals['Imposta'] = vals['Imposta'] / exchange_rate

    def _get_tax_comunicazione_dati_iva(self):
        self.ensure_one()
        fattura = self
        tax_model = self.env['account.tax']

        tax_lines = []
        tax_grouped = {}
        for tax_line in fattura.tax_line:
            tax = tax_model.search([
                ('tax_code_id', '=', tax_line.tax_code_id.id)
            ], limit=1)
            if not tax:
                raise UserError(
                    _("Tax with code {tax_code} not found")
                    .format(
                        tax_code=tax_line.tax_code_id.display_name))
            aliquota = tax.amount * 100
            parent = tax_model.search([('child_ids', 'in', [tax.id])])
            if parent:
                main_tax = parent
                aliquota = parent.amount * 100
            else:
                main_tax = tax
            kind_id = main_tax.kind_id.id
            payability = main_tax.payability
            imposta = tax_line.amount
            base = tax_line.base
            if main_tax.id not in tax_grouped:
                tax_grouped[main_tax.id] = {
                    'ImponibileImporto': 0,
                    'Imposta': imposta,
                    'Aliquota': aliquota,
                    'Natura_id': kind_id,
                    'EsigibilitaIVA': payability,
                    'Detraibile': 0.0,
                }
                if fattura.type in ('in_invoice', 'in_refund'):
                    tax_grouped[main_tax.id]['Detraibile'] = 100.0
            else:
                tax_grouped[main_tax.id]['Imposta'] += imposta
            if not tax.account_collected_id:
                # account_collected_id è valorizzato per la parte
                # detraibile dell'imposta
                # In questa tax_line è presente il totale dell'imponibile
                # per l'imposta corrente
                tax_grouped[main_tax.id]['ImponibileImporto'] += base

        for tax_id in tax_grouped:
            tax = tax_model.browse(tax_id)
            vals = tax_grouped[tax_id]
            if tax.child_ids:
                perc_detraibile = 0.0
                for child_tax in tax.child_ids:
                    if not child_tax.account_collected_id:
                        perc_detraibile = (1 - child_tax.amount) * 100.0
                        break
                if vals['Aliquota'] and perc_detraibile:
                    vals['Detraibile'] = perc_detraibile
                else:
                    vals['Detraibile'] = 0.0
            vals = self._check_tax_comunicazione_dati_iva(tax, vals)
            fattura._compute_taxes_in_company_currency(vals)
            tax_lines.append((0, 0, vals))

        return tax_lines

    def _check_tax_comunicazione_dati_iva(self, tax, val=None):
        self.ensure_one()
        if not val:
            val = {}
        if val['Aliquota'] == 0 and not val['Natura_id']:
            raise ValidationError(
                _(
                    "Please specify exemption kind for tax: {} - Invoice {}"
                ).format(tax.name, self.number or False))
        if not val['EsigibilitaIVA']:
            raise ValidationError(
                _(
                    "Please specify VAT payability for tax: {} - Invoice {}"
                ).format(tax.name, self.number or False))
        return val
