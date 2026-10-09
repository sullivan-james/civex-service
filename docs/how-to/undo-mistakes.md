# Undo a mistake

**Goal:** put back a value someone overwrote, or bring back something deleted.
Every change is recorded, and deletes are reversible until you choose to purge.

## Put back an edit

Find the change in the record's history:

```bash
civex history record 2d69dc46
```

```text
Entry     When              Action  Changes
077ba5fe  2026-10-09 12:09  update  Site: North Ridge → East Point
6d774cad  2026-10-09 12:07  create  Site: (none) → North Ridge
```

Revert it. civex shows what goes back and asks first:

```bash
civex history revert 077ba5fe
civex history revert 077ba5fe --field site        # only some fields
civex history revert 077ba5fe --force             # even fields edited since
```

A field that was edited again after that entry is left alone unless you pass
`--force`. The revert is itself a change, so it can be reverted too.

**In the app:** the record's **History** tab, click the entry, then
**Revert…**. It shows each field as it is and as it would become.

## Bring back a deleted record

```bash
civex trash list
```

```text
Type    Name            ID        Deleted
record  1 in humpbacks  bfcdc007  today
Retention: 30 day(s). Restore with `civex schema|collection|record restore <name/id>` …
```

```bash
civex record restore bfcdc007
```

```text
Restored record 'bfcdc007'.
```

A record comes back with the children that were deleted with it. To be choosy:

```bash
civex record restore bfcdc007 --only-this      # leave its children deleted
civex record restore bfcdc007 --with-parents   # also bring back deleted records above it
```

**In the app:** **Activity** in the sidebar → press **Deleted** → **Restore** on
the row. A bulk delete is one row ("Deleted 71 records"): **Restore** brings all
of it back, or open it and tick only the records you want.

## Bring back a field, schema or collection

```bash
civex schema restore trial
civex collection restore study-2024
civex trash list --kind field                  # find the field's id
civex schema restore-field trial <field-id>    # values come back too
```

Restoring a schema or collection brings back the records deleted *with* it, not
ones you had deleted separately before.

## When a restore is refused

| Message says | Why | Do |
|---|---|---|
| its collection / schema / parent is deleted | It would come back somewhere it can't be seen | Restore that first (the app offers it) |
| another record has these values | A [uniqueness rule](../guides/schemas-and-fields.md#keeping-records-unique) would break | Change or delete the other record |
| a field with this name exists | A new field took the deleted one's name | Rename or delete the new field |

## How long you have

Deleted items stay restorable until they are purged. Nothing is purged by
itself. A clean-up you run purges what was deleted more than
`purge_after_days` ago (30 by default), and only if that is switched on in
Settings → Retention:

```bash
civex retention show
```

Purging (`civex record purge <id>`, **Delete permanently**) can't be undone and
removes the record's history too, leaving only a note that it existed.

## See also

- [Deleting & restoring data](../guides/deleting-and-restoring.md): cascades,
  partial restores and retention in detail.
