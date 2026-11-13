from odoo import _, fields, models
from odoo.exceptions import UserError

APPROVER_GROUP = 'pricelist_approval.group_pricelist_approver'


class PricelistApprovalMixin(models.AbstractModel):
    """Turn writes on a model into change requests that wait for approval.

    The mixin compares the incoming values with the current ones *before*
    anything is written. Fields that really change are stored on a
    ``pricelist.change.request`` and left untouched on the record; they are
    written only when an approver accepts the request.

    Approval is enforced per company, and only when that company has an
    approver configured. Two kinds of write go straight through:

    * writes by members of the approver group;
    * writes in superuser mode. This is how an approved request is applied,
      and it keeps module upgrades and server-side flows working. There is
      deliberately no context key to skip the check: context comes from the
      client, so any user could send it.
    """

    _name = 'pricelist.approval.mixin'
    _description = 'Pricelist Approval Mixin'

    pending_change_request_id = fields.Many2one(
        comodel_name='pricelist.change.request',
        string="Pending Change Request",
        compute='_compute_pending_change_request_id',
    )

    def _compute_pending_change_request_id(self):
        requests = self.env['pricelist.change.request'].search([
            ('res_model', '=', self._name),
            ('res_id', 'in', self._origin.ids),
            ('state', '=', 'pending'),
        ])
        request_by_res_id = {request.res_id: request for request in requests}
        for record in self:
            record.pending_change_request_id = request_by_res_id.get(record._origin.id, False)

    # ------------------------------------------------------------------
    # Hooks for the inheriting models
    # ------------------------------------------------------------------

    def _pricelist_approval_pricelist(self):
        """Return the pricelist this record belongs to."""
        raise NotImplementedError

    def _pricelist_approval_company(self):
        """Return the company whose approver reviews changes to this record.

        A pricelist shared between companies has no company of its own, so the
        current company of the user decides.
        """
        self.ensure_one()
        return self._pricelist_approval_pricelist().company_id or self.env.company

    def _pricelist_approval_tracked_fields(self, vals):
        """Return the names in ``vals`` that need approval.

        Relational lists (``item_ids`` on a pricelist, for instance) are left
        out: their commands end up as writes on the lines, which are tracked
        on their own model.
        """
        return [
            name for name in vals
            if name in self._fields
            and self._fields[name].store
            and self._fields[name].type not in ('one2many', 'many2many')
            and name not in models.MAGIC_COLUMNS
        ]

    # ------------------------------------------------------------------
    # Write interception
    # ------------------------------------------------------------------

    def write(self, vals):
        if self.env.su:
            return super().write(vals)

        tracked = self._pricelist_approval_tracked_fields(vals)
        changes = {}
        for record in self:
            if not record._pricelist_approval_company().pricelist_approver_id:
                continue
            change = record._pricelist_approval_diff(vals, tracked)
            if not change:
                continue
            if record.pending_change_request_id:
                raise UserError(_(
                    "%(record)s already has a change waiting for approval (%(request)s). "
                    "It must be approved or rejected before the record can be changed again.",
                    record=record.display_name,
                    request=record.pending_change_request_id.name,
                ))
            changes[record.id] = change

        if not changes or self.env.user.has_group(APPROVER_GROUP):
            return super().write(vals)

        held = self.browse(changes)
        direct = self - held
        if direct:
            super(PricelistApprovalMixin, direct).write(vals)
        untracked_vals = {name: value for name, value in vals.items() if name not in tracked}
        if untracked_vals:
            super(PricelistApprovalMixin, held).write(untracked_vals)
        held._pricelist_approval_create_requests(changes)
        return True

    def _pricelist_approval_diff(self, vals, tracked):
        """Return ``{'old': {...}, 'new': {...}}`` for the tracked fields that
        ``vals`` would really change on this record, or ``None``."""
        self.ensure_one()
        old, new = {}, {}
        for name in tracked:
            field = self._fields[name]
            current = self._pricelist_approval_serialize(field, self[name])
            # Normalise the incoming value the way the ORM would, so that
            # 10 and 10.0, or a date and its string, compare as equal.
            incoming = field.convert_to_record(field.convert_to_cache(vals[name], self), self)
            incoming = self._pricelist_approval_serialize(field, incoming)
            if incoming != current:
                old[name] = current
                new[name] = incoming
        return {'old': old, 'new': new} if new else None

    @staticmethod
    def _pricelist_approval_serialize(field, value):
        """Make a field value storable in JSON and usable again in ``write``."""
        if field.type == 'many2one':
            return value.id or False
        if field.type == 'date':
            return fields.Date.to_string(value) or False
        if field.type == 'datetime':
            return fields.Datetime.to_string(value) or False
        return value

    def _pricelist_approval_create_requests(self, changes):
        # Users have read access only on change requests, so that a request
        # can only come from an intercepted write.
        requests = self.env['pricelist.change.request'].sudo().create([{
            'res_model': record._name,
            'res_id': record.id,
            'pricelist_id': record._pricelist_approval_pricelist().id,
            'company_id': record._pricelist_approval_company().id,
            'requested_by': self.env.uid,
            'old_values': changes[record.id]['old'],
            'new_values': changes[record.id]['new'],
        } for record in self])
        self.invalidate_recordset(['pending_change_request_id'])
        return requests
