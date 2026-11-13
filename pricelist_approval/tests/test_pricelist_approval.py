from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged

ACTIVITY_TYPE = 'pricelist_approval.mail_activity_type_pricelist_approval'


@tagged('post_install', '-at_install')
class TestPricelistApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.editor = new_test_user(
            cls.env, login='pricelist_editor',
            groups='base.group_user,product.group_product_manager,product.group_product_pricelist',
        )
        cls.approver = new_test_user(
            cls.env, login='pricelist_approver',
            groups='base.group_user,product.group_product_manager,'
                   'pricelist_approval.group_pricelist_approver',
        )
        cls.product = cls.env['product.template'].create({'name': "Desk", 'list_price': 100.0})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': "Retail",
            'company_id': cls.company.id,
            'item_ids': [(0, 0, {
                'applied_on': '1_product',
                'product_tmpl_id': cls.product.id,
                'compute_price': 'fixed',
                'fixed_price': 80.0,
            })],
        })
        cls.item = cls.pricelist.item_ids
        cls.company.pricelist_approver_id = cls.approver
        cls.Request = cls.env['pricelist.change.request']

    def _requests(self, record):
        return self.Request.search([('res_model', '=', record._name), ('res_id', '=', record.id)])

    # ------------------------------------------------------------------
    # Interception
    # ------------------------------------------------------------------

    def test_change_is_held_until_approved(self):
        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})

        self.assertEqual(self.pricelist.name, "Retail", "the change must not be applied yet")
        request = self._requests(self.pricelist)
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, 'pending')
        self.assertEqual(request.requested_by, self.editor)
        self.assertEqual(request.old_values, {'name': "Retail"})
        self.assertEqual(request.new_values, {'name': "Retail 2027"})
        self.assertEqual(self.pricelist.pending_change_request_id, request)
        self.assertEqual(self.pricelist.pending_change_request_count, 1)
        activity = request.activity_ids
        self.assertEqual(activity.user_id, self.approver)
        self.assertEqual(activity.activity_type_id, self.env.ref(ACTIVITY_TYPE))

        request.with_user(self.approver).action_approve()

        self.assertEqual(self.pricelist.name, "Retail 2027")
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.reviewed_by, self.approver)
        self.assertFalse(request.activity_ids, "the approver's activity must be closed")
        self.assertFalse(self.pricelist.pending_change_request_id)

    def test_rejected_change_is_discarded(self):
        self.item.with_user(self.editor).write({'fixed_price': 60.0})
        request = self._requests(self.item)

        action = request.with_user(self.approver).action_reject()
        wizard = Form(self.env[action['res_model']].with_user(self.approver).with_context(action['context']))
        wizard.reason = "Below cost"
        wizard.save().action_confirm()

        self.assertEqual(self.item.fixed_price, 80.0)
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.rejection_reason, "Below cost")
        self.assertFalse(self.item.pending_change_request_id)
        # The record is free again once the request is closed.
        self.item.with_user(self.editor).write({'fixed_price': 70.0})
        self.assertEqual(len(self._requests(self.item)), 2)

    def test_rule_edited_from_the_pricelist_form(self):
        """The web client saves rule edits as commands on the pricelist."""
        self.pricelist.with_user(self.editor).write({
            'item_ids': [(1, self.item.id, {'fixed_price': 50.0, 'min_quantity': 5})],
        })

        self.assertEqual(self.item.fixed_price, 80.0)
        self.assertFalse(self._requests(self.pricelist), "the pricelist itself did not change")
        request = self._requests(self.item)
        self.assertEqual(request.pricelist_id, self.pricelist)
        self.assertEqual(request.new_values, {'fixed_price': 50.0, 'min_quantity': 5.0})
        self.assertEqual(self.pricelist.pending_change_request_count, 1)

        request.with_user(self.approver).action_approve()
        self.assertEqual(self.item.fixed_price, 50.0)
        self.assertEqual(self.item.min_quantity, 5)

    def test_only_real_changes_are_held(self):
        self.pricelist.with_user(self.editor).write({'name': "Retail"})
        self.item.with_user(self.editor).write({'fixed_price': 80, 'product_tmpl_id': self.product.id})

        self.assertFalse(self._requests(self.pricelist))
        self.assertFalse(self._requests(self.item))

    def test_record_is_locked_while_a_change_is_pending(self):
        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})

        with self.assertRaises(UserError):
            self.pricelist.with_user(self.editor).write({'name': "Retail 2028"})
        with self.assertRaises(UserError, msg="approvers must close the request first too"):
            self.pricelist.with_user(self.approver).write({'name': "Retail 2028"})

    def test_mixed_recordset(self):
        """One write on several records holds only the records that change."""
        other = self.pricelist.copy({'name': "Wholesale"})

        (self.pricelist | other).with_user(self.editor).write({'name': "Wholesale"})

        self.assertEqual(self.pricelist.name, "Retail")
        self.assertEqual(len(self._requests(self.pricelist)), 1)
        self.assertFalse(self._requests(other))

    # ------------------------------------------------------------------
    # Who is exempt
    # ------------------------------------------------------------------

    def test_no_approver_means_no_approval(self):
        self.company.pricelist_approver_id = False

        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})

        self.assertEqual(self.pricelist.name, "Retail 2027")
        self.assertFalse(self._requests(self.pricelist))

    def test_approver_changes_apply_directly(self):
        self.item.with_user(self.approver).write({'fixed_price': 75.0})

        self.assertEqual(self.item.fixed_price, 75.0)
        self.assertFalse(self._requests(self.item))

    def test_context_cannot_skip_the_approval(self):
        """Context is client-controlled, so no key in it may bypass the check."""
        self.item.with_user(self.editor).with_context(
            skip_pricelist_approval_check=True, pricelist_approval_bypass=True,
        ).write({'fixed_price': 1.0})

        self.assertEqual(self.item.fixed_price, 80.0)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def test_only_approvers_review(self):
        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})
        request = self._requests(self.pricelist)

        with self.assertRaises(AccessError):
            request.with_user(self.editor).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.editor)._action_reject("no")
        with self.assertRaises(AccessError, msg="requests come from intercepted writes only"):
            self.Request.with_user(self.editor).create({
                'res_model': 'product.pricelist',
                'res_id': self.pricelist.id,
                'pricelist_id': self.pricelist.id,
                'company_id': self.company.id,
                'new_values': {'name': "Hacked"},
            })
        self.assertEqual(self.pricelist.name, "Retail")

    def test_reviewed_request_cannot_be_reviewed_again(self):
        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})
        request = self._requests(self.pricelist)
        request.with_user(self.approver).action_approve()

        with self.assertRaises(UserError):
            request.with_user(self.approver).action_approve()

    def test_approver_must_be_in_the_approver_group(self):
        with self.assertRaises(ValidationError):
            self.company.pricelist_approver_id = self.editor

    def test_requests_are_company_scoped(self):
        other_company = self.env['res.company'].create({'name': "Other Co"})
        outsider = new_test_user(
            self.env, login='pricelist_outsider', groups='base.group_user',
            company_id=other_company.id, company_ids=[(6, 0, other_company.ids)],
        )
        self.pricelist.with_user(self.editor).write({'name': "Retail 2027"})

        self.assertFalse(self.Request.with_user(outsider).search([]))

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def test_summary_is_readable_and_escaped(self):
        category = self.env['product.category'].create({'name': "<b>Office</b>"})
        self.item.with_user(self.editor).write({
            'applied_on': '2_product_category',
            'categ_id': category.id,
        })
        summary = self._requests(self.item).change_summary

        self.assertIn("&lt;b&gt;Office&lt;/b&gt;", summary, "user text must be escaped")
        self.assertNotIn("<b>Office</b>", summary)
        self.assertIn("Category", summary, "selection values are shown by label")
        self.assertNotIn("2_product_category", summary)
