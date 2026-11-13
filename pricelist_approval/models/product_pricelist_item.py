from odoo import models


class ProductPricelistItem(models.Model):
    _name = 'product.pricelist.item'
    _inherit = ['product.pricelist.item', 'pricelist.approval.mixin']

    def _pricelist_approval_pricelist(self):
        return self.pricelist_id
