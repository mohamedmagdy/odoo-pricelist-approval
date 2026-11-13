from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .pricelist_approval_mixin import APPROVER_GROUP


class ResCompany(models.Model):
    _inherit = 'res.company'

    pricelist_approver_id = fields.Many2one(
        comodel_name='res.users',
        string="Pricelist Approver",
        domain=[('share', '=', False)],
        help="Changes to pricelists and pricelist rules of this company wait for this user's "
             "approval. Leave empty to apply changes immediately.",
    )

    @api.constrains('pricelist_approver_id')
    def _check_pricelist_approver_id(self):
        approver_group = self.env.ref(APPROVER_GROUP)
        for company in self:
            approver = company.pricelist_approver_id
            if approver and approver_group not in approver.groups_id:
                raise ValidationError(_(
                    "%(user)s cannot be the pricelist approver of %(company)s: "
                    "add the user to the \"%(group)s\" group first.",
                    user=approver.name,
                    company=company.name,
                    group=approver_group.name,
                ))
