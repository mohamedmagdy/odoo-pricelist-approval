from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pricelist_approver_id = fields.Many2one(
        related='company_id.pricelist_approver_id',
        readonly=False,
    )
