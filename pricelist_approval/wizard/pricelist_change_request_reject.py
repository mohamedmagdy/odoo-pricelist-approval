from odoo import fields, models


class PricelistChangeRequestReject(models.TransientModel):
    _name = 'pricelist.change.request.reject'
    _description = 'Reject Pricelist Change Requests'

    request_ids = fields.Many2many(comodel_name='pricelist.change.request', required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_ids._action_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
