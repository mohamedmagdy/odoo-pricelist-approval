from odoo import _, fields, models


class ProductPricelist(models.Model):
    _name = 'product.pricelist'
    _inherit = ['product.pricelist', 'pricelist.approval.mixin']

    pending_change_request_count = fields.Integer(
        string="Pending Changes",
        compute='_compute_pending_change_request_count',
        help="Changes to this pricelist or to its rules that wait for approval.",
    )

    def _compute_pending_change_request_count(self):
        counts = dict(self.env['pricelist.change.request']._read_group(
            domain=[('pricelist_id', 'in', self.ids), ('state', '=', 'pending')],
            groupby=['pricelist_id'],
            aggregates=['__count'],
        ))
        for pricelist in self:
            pricelist.pending_change_request_count = counts.get(pricelist, 0)

    def _pricelist_approval_pricelist(self):
        return self

    def action_open_pending_change_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pending Changes"),
            'res_model': 'pricelist.change.request',
            'view_mode': 'list,form',
            'domain': [('pricelist_id', '=', self.id), ('state', '=', 'pending')],
        }
