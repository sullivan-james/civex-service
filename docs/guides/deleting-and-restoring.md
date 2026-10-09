# Deleting & restoring data

Deleting a schema, field, collection or record is reversible. It is hidden from
lists, search and exports, and stays restorable until it is **purged**, which
only happens when you choose to. For the short version, see
[Undo a mistake](../how-to/undo-mistakes.md).

(This is not `civex dump` / `civex restore`, which copy a whole project. See
[Back up a project](../how-to/back-up.md).)

## What a delete takes with it

| Delete | Also deletes | Notes |
|---|---|---|
| Record | Every record inside it, recursively | Refused while another record links to it through a `reference` field, unless `--force` (which clears those links) |
| Collection | Every record in it | |
| Schema | Every record of that schema, in every collection | Records of other schemas beneath them stay |
| Field | Nothing | Records keep their values for it, shown under **Deleted fields** on the record |

```bash
civex record delete <id>
civex collection delete study-2024
civex schema delete trial
civex schema remove-field trial score
```

## Restoring

```bash
civex trash list                              # newest first; --kind, --search
civex record restore <id>
civex collection restore study-2024
civex schema restore trial
civex schema restore-field trial <field id>   # id from: civex trash list --kind field
```

**In the app:** **Activity** → **Deleted** → **Restore** on the row, or
**Restore all N** for everything listed. Each shows what comes back before doing
it, and links to it afterwards.

### Only what that delete took

A delete stamps everything it takes with one time, and a restore brings back
exactly that: restoring a collection doesn't bring back a record you had deleted
from it the week before.

### Choosing part of it

A bulk or tree delete is **one line** in Activity ("Deleted 71 records").

- **Restore** on the line brings it all back, parents first.
- Open the line, tick some records, and **Restore N selected**. A ticked record
  whose parent is deleted brings the parent back too, by itself.

For one record:

```bash
civex record restore <id>                        # with what was deleted with it
civex record restore <id> --only-this            # leave its children deleted
civex record restore <id> --with-parents         # and the deleted records above it
```

### When a restore is refused

| Because | Do |
|---|---|
| Its collection, schema or parent record is still deleted | Restore that first. The app offers **Restore the collection "…" instead** |
| Another record now has its [unique](schemas-and-fields.md#keeping-records-unique) values | Change or delete that record. Bulk restores leave these and report them |
| A field: another field took its name | Rename or delete that field |
| A field: its schema is deleted | Restore the schema first |

**Records under a deleted record.** Rarely, history leaves a live record under a
deleted parent. Its page says so, with **Restore …** to put the parent back, and
`civex record orphans` lists any. `civex doctor` counts them.

## Purging (permanent)

```bash
civex record purge <id>              # must be deleted first
civex collection purge study-2024
civex schema purge trial
civex trash purge-expired            # everything deleted longer ago than purge_after_days
```

**In the app:** open the deleted item in Activity → **Delete permanently**.

Purging can't be undone. It removes the thing, everything deleted with it, and
**every history entry about the records removed**. History keeps one note per
record (its id, schema, collection, and when it was created and purged), shown
in Activity as *Gone for good*. Deleted fields aren't purged yet. They stay
restorable until their schema is purged.

Records purged by an older civex may still have values in history:
**Settings → Retention** offers to remove them (`civex retention forget-purged`).

## Retention: keeping less

Deleted items, history and finished workflow runs are kept forever unless you
set limits. **Nothing is removed by itself**: a **clean-up** applies the limits
when you (or a cron job) run it, and always counts first.

| Kind | Setting (`[retention]` in `config.toml`) | A clean-up… |
|---|---|---|
| Deleted items | `purge_after_days` (30), `auto_purge_deleted` (off) | purges items deleted longer ago, only if `auto_purge_deleted` is on |
| History | `audit_days` (forever) | removes older entries |
| Workflow runs | `run_days` (forever) | removes finished runs and their logs |

```bash
civex retention show                                   # settings, and what would go now
civex retention run --settings                         # apply them (asks first)
civex retention run --history-before 2026-01-01 --dry-run
civex retention run --deleted-before 2026-01-01 --runs-before 2026-01-01
```

**In the app:** **Settings → Retention**, then **Clean up now…**, or pick dates
under **Delete everything before a date**. You type `delete` to confirm.

Always kept: history about anything you can still restore, each existing thing's
first and latest entry, runs still waiting or running, and a deleted parent while
anything beneath it remains. Files freed by a clean-up are removed by
[storage clean-up](storage.md#cleaning-up) (`civex store gc`).
