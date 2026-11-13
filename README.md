# Pricelist Approval for Odoo 18

Holds changes to pricelists and pricelist rules until an approver accepts them.

A salesperson edits a price as usual. The change is not applied: it is stored as a
change request, the approver gets an activity, and the old price stays in force
until the request is approved. Rejected requests are discarded with a reason.

Works on Odoo 18 Community and Enterprise. Depends only on `sale`.

## How it works

| Step | What happens |
|---|---|
| A user saves a pricelist or a rule | The write is compared with the current values. Fields that really change go into a `pricelist.change.request`; the record keeps its old values. |
| The approver opens the request | The form shows each field with its current and requested value. |
| Approve | The stored values are written to the record and the requester is notified. |
| Reject | Nothing is written. The reason is stored and sent to the requester. |

While a request is pending, the record cannot be changed again by anyone.

## Design notes

- **Compare first, then write.** The interception computes the difference before
  anything reaches the database, so a held change never exists on the record, not
  even inside the transaction. Unchanged values (saving a form without edits,
  `10` versus `10.0`) create no request.
- **One mixin, two models.** `pricelist.approval.mixin` carries the logic;
  `product.pricelist` and `product.pricelist.item` only say which pricelist and
  company they belong to. Rule edits made from the pricelist form arrive as
  commands on `item_ids` and are caught on the rule model.
- **No context bypass.** Context is sent by the client, so a key such as
  `skip_approval` could be set by any user over RPC. Only superuser mode skips the
  check, which is how an approved request is applied.
- **Requests cannot be forged.** Users have read access only; requests are created
  by the interception itself. Approving checks the approver group in Python, not
  only in the view.
- **Escaped summary.** The comparison table is built with `Markup`, so text typed
  into a pricelist cannot inject HTML into the approver's screen.
- **Multi-company.** Each company has its own approver; a record rule limits
  requests to the user's companies. A company without an approver has no approval
  step.

## Configuration

1. Add the approver to the **Pricelist Approver** group.
2. In **Sales > Configuration > Settings > Pricing**, set **Pricelist Approval** to
   that user.
3. Requests are listed under **Sales > Products > Pricelist Change Requests**.

Members of the approver group are trusted: their own edits apply directly.

## Known limits

- Creating and deleting rules is not held, only changes to existing ones.
- Server-side code running in superuser mode (`sudo()`) is not held.

## Tests

14 tests cover the interception, the exemptions, access rights, multi-company
scoping and the escaping of the summary.

```bash
odoo-bin -d test_db -i pricelist_approval --test-tags /pricelist_approval --stop-after-init
```

## License

LGPL-3. See [LICENSE](LICENSE).
