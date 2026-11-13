from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .pricelist_approval_mixin import APPROVER_GROUP

ACTIVITY_TYPE = 'pricelist_approval.mail_activity_type_pricelist_approval'


class PricelistChangeRequest(models.Model):
    _name = 'pricelist.change.request'
    _description = 'Pricelist Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string="Reference", required=True, readonly=True, copy=False, default=lambda self: _("New"),
    )
    state = fields.Selection(
        selection=[
            ('pending', "Pending"),
            ('approved', "Approved"),
            ('rejected', "Rejected"),
        ],
        default='pending', required=True, readonly=True, copy=False, tracking=True,
    )
    res_model = fields.Selection(
        selection=[
            ('product.pricelist', "Pricelist"),
            ('product.pricelist.item', "Pricelist Rule"),
        ],
        string="Change On", required=True, readonly=True,
    )
    res_id = fields.Many2oneReference(
        string="Record ID", model_field='res_model', required=True, readonly=True,
    )
    resource_name = fields.Char(string="Record", compute='_compute_resource_name')
    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist', required=True, readonly=True, ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(comodel_name='res.company', required=True, readonly=True)
    requested_by = fields.Many2one(
        comodel_name='res.users', required=True, readonly=True, default=lambda self: self.env.user,
    )
    reviewed_by = fields.Many2one(comodel_name='res.users', readonly=True, copy=False)
    review_date = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)
    old_values = fields.Json(readonly=True)
    new_values = fields.Json(readonly=True)
    change_summary = fields.Html(compute='_compute_change_summary')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    def _get_target(self):
        """Return the record this request changes (empty if it was deleted)."""
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id).exists()

    @api.depends('res_model', 'res_id')
    def _compute_resource_name(self):
        for request in self:
            target = request.res_model and request._get_target()
            request.resource_name = target.display_name if target else _("Deleted record")

    @api.depends('res_model', 'old_values', 'new_values')
    def _compute_change_summary(self):
        row = Markup("<tr><td>%s</td><td>%s</td><td>%s</td></tr>")
        table = Markup(
            '<table class="table table-sm"><thead><tr>'
            "<th>%s</th><th>%s</th><th>%s</th>"
            "</tr></thead><tbody>%s</tbody></table>"
        )
        for request in self:
            if not request.res_model or not request.new_values:
                request.change_summary = False
                continue
            model = self.env[request.res_model]
            old_values = request.old_values or {}
            # Markup's % escapes its arguments, so values typed by users cannot
            # inject HTML into the summary.
            rows = Markup().join(
                row % (
                    model._fields[name].get_description(self.env, ['string'])['string'],
                    request._format_value(model._fields[name], old_values.get(name)),
                    request._format_value(model._fields[name], new_value),
                )
                for name, new_value in request.new_values.items()
                if name in model._fields
            )
            request.change_summary = table % (_("Field"), _("Current value"), _("New value"), rows)

    def _format_value(self, field, value):
        if field.type == 'boolean':
            return _("Yes") if value else _("No")
        if value is None or value is False or value == '':
            return ''
        if field.type == 'many2one':
            # sudo: the reader of a request may not have access to the related model.
            record = self.env[field.comodel_name].sudo().browse(value).exists()
            return record.display_name if record else _("Deleted record")
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, value)
        return str(value)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('pricelist.change.request') or _("New")
                )
        requests = super().create(vals_list)
        for request in requests:
            approver = request.company_id.pricelist_approver_id
            if approver:
                request.activity_schedule(
                    ACTIVITY_TYPE,
                    user_id=approver.id,
                    summary=_("Review change on %s", request.resource_name),
                )
        return requests

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def _check_can_review(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(_("Only pricelist approvers can review change requests."))
        if any(request.state != 'pending' for request in self):
            raise UserError(_("Only pending change requests can be reviewed."))

    def action_approve(self):
        self._check_can_review()
        for request in self:
            target = request._get_target()
            if not target:
                raise UserError(_(
                    "%s refers to a record that no longer exists. Reject it instead.",
                    request.name,
                ))
            # sudo: the approver's decision is the authorisation, and superuser
            # mode is what lets the write through the approval mixin.
            target.sudo().write(request.new_values)
        self._set_reviewed('approved')
        return True

    def action_reject(self):
        self._check_can_review()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Change Request"),
            'res_model': 'pricelist.change.request.reject',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_ids': self.ids},
        }

    def _action_reject(self, reason):
        self._check_can_review()
        self._set_reviewed('rejected', rejection_reason=reason)

    def _set_reviewed(self, state, **extra_vals):
        self.write({
            'state': state,
            'reviewed_by': self.env.uid,
            'review_date': fields.Datetime.now(),
            **extra_vals,
        })
        self.activity_feedback([ACTIVITY_TYPE])
        for request in self:
            if state == 'approved':
                body = _("Your change on %s was approved and applied.", request.resource_name)
            else:
                body = _(
                    "Your change on %(record)s was rejected: %(reason)s",
                    record=request.resource_name,
                    reason=request.rejection_reason,
                )
            request.message_post(body=body, partner_ids=request.requested_by.partner_id.ids)
            target = request._get_target()
            if target:
                target.invalidate_recordset(['pending_change_request_id'])
