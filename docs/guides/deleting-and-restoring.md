# Deleting & restoring data

Deleting a schema, field, collection or record in civex is reversible. A delete
sets a `deleted_at` timestamp instead of removing the row; the item is
excluded from normal listings, search and CSV export, but stays recoverable
in **Recently Deleted** until it's purged.

This is separate from `civex dump` / `civex restore`, which back up and
reload an entire project from a YAML file (see
[Exporting and restoring](collections-and-records.md#exporting-and-restoring)).
The commands on this page undo a single delete, moments or days after it
happened, without touching anything else.

## Deleting

=== "CLI"
    ```bash
    civex schema delete trial
    civex schema remove-field trial score
    civex collection delete study-2024
    civex record delete <record-id>
    ```

=== "Web UI"
    **Delete** on a schema, collection or record's detail page, or the **✕** on a field.

## Cascades

Deleting a **schema** also soft-deletes every record typed by it, across
every collection — a record type never leaves its own records behind.
Records of a *different* schema that reference one of those records as a
parent are left alone; they stay visible, pointing at a hidden parent,
until it's restored.

Deleting a **collection** also soft-deletes every record in it.

Deleting a **field** hides it from its schema and leaves every record's value
for it where it is, so nothing is lost: a record shows the value under
**Deleted fields** until the field is restored.

Deleting a **record** also soft-deletes its children (records that name it
as their parent record), recursively — the same cascade civex has always
applied to record deletes. If another record still references the one
being deleted through a `reference`/`reference_list` field, the delete is
blocked unless `--force`/`force=true` is passed, in which case those
fields are cleared instead.

## Restoring

=== "CLI"
    ```bash
    civex trash list                 # everything currently in Recently Deleted
    civex schema restore trial
    civex schema restore-field trial <field-id>   # the ID is in `civex trash list --kind field`
    civex collection restore study-2024
    civex record restore <record-id>
    ```

=== "Web UI"
    Go to **Activity** in the sidebar and press **Deleted**. Search or filter to find the item, and click **Restore** on its row; or click **Restore all N** to restore everything listed. A deletion that took many records with it (a bulk delete, a tree) is one line. A window says what will come back and where it will go, and after you confirm, a message names what was restored and links to it.

A record can also be refused because a schema's [uniqueness rule](schemas-and-fields.md#keeping-records-unique) would be broken: another record took its values while it was deleted. The Restore window names that record and offers to open it; change or delete it, then restore. Bulk restores skip such records and report them as held back.

Restoring a **field** brings it back to its schema with every record's value for
it. It can't come back while its schema is deleted (restore the schema first;
the window offers it), or while another field on the schema has taken its name
(rename or delete that one first). A record whose schema was deleted says so,
and when, on its page, with a **Restore…** button.

Deleting a record that has children is **one line** in Activity ("Deleted 71
records"). Press **Restore** on that line to put back everything that delete
took, parent first, after it says how many records come back. The same button
is inside the line's window (**Restore everything…**). You don't need to find
the parent among its children, and you are never forced to take it all back:
the line's window (click it) lists the records it took, and you can **tick the
ones you want** and press **Restore N selected**. A selected record under a
deleted parent brings that parent back too, by itself, so it can be seen; the
rest stay deleted. **Choose which…** in the Restore window gets you there.

The same choice is open for a single record. Restoring one selection of a
deleted recording offers **Restore only this** (the selection and the recording
it sits under), **this and what was deleted with it**, or the recording with
everything deleted alongside it. A record that has children deleted with it
offers **Restore only this** beside restoring them all. On the command line:

```bash
civex record restore <id> --only-this                  # not the children deleted with it
civex record restore <id> --with-parents               # bring back the deleted records above it, each by itself
civex record restore <id> --only-this --with-parents
```

Restoring a schema or collection brings back the records that were deleted
*with* it, and restoring a record brings back the children deleted with it.
Anything you had deleted on its own earlier stays in Recently Deleted, so you
get back what that one delete took and nothing else.

A record can't be restored while something above it is still deleted — its
collection, its schema, or a parent record — because it would come back
somewhere it can't be seen. Restoring it says what is in the way. In the web
UI the window offers **Restore the collection “…” instead** (or the schema, or
parent record); that brings back everything deleted with it, and the record
along with it. On the command line, restore the item named in the message
first. Undoing a delete from a record's History follows the same rules.

## Retention and permanent deletion

Deleted items can be restored for a number of days (`purge_after_days`, default 30). Reaching that age doesn't delete anything by itself. Permanent deletion is a separate, explicit step, or something you switch on for clean-ups to do (see below):

=== "CLI"
    ```bash
    civex schema purge trial              # must already be deleted
    civex collection purge study-2024
    civex record purge <record-id>
    civex trash purge-expired             # purge everything past the retention window
    ```

=== "Web UI"
    Open the deleted item in **Activity** (press **Deleted**) and choose **Delete permanently**.

A deleted field is not purged by the retention clean-up or `civex trash purge-expired` yet: it stays restorable until the schema it belongs to is purged.

Purging is irreversible: it removes the row (and, for a schema or collection, everything cascade-deleted with it) for good, **and every history entry about the records removed**. What it held is not kept anywhere in the change history. For each record, history keeps one note, a *tombstone*: that it was permanently deleted, when, its ID, and its schema and collection. That is what **Activity** shows as *Gone for good*. A permanently deleted collection or schema keeps its own entry (its name is not record data) and its records leave no notes of their own.

For records that were permanently deleted before this was so, **Settings → Retention** shows how many history entries still hold their values and offers to delete them (leaving each the tombstone); on the command line, `civex retention forget-purged`.

## Keeping less: retention settings and clean-ups

Three things grow without limit unless you say otherwise: deleted items, the change history, and finished workflow runs with their step logs. **Settings → Retention** sets how long to keep each (the default for all of them is forever):

| Kind | Setting | What a clean-up does |
|---|---|---|
| Deleted items | restorable for *N* days, and **Delete them for good when cleaning up** | permanently deletes what was deleted longer ago than that, if the switch is on |
| Change history | keep for *N* days, or forever | removes older entries |
| Workflow runs and logs | keep for *N* days, or forever | removes finished runs, and their step logs, that are older |

Nothing is removed by itself. A **clean-up** applies the settings, or deletes everything before a date you choose, separately for each kind. It always counts first and shows you what would go, and you type `delete` to confirm.

=== "CLI"
    ```bash
    civex retention show                                  # what is kept, and what a clean-up would remove now
    civex retention run --settings                        # apply the settings (asks first)
    civex retention run --history-before 2026-01-01       # or by date, per kind:
    civex retention run --deleted-before 2026-01-01 --runs-before 2026-01-01 --dry-run
    ```

=== "Web UI"
    **Settings → Retention**: set the periods and **Save**; then **Clean up now…** to apply them, or pick dates under **Delete everything before a date** and **Preview…**.

Some history is always kept: entries about something you can still restore (so *Deleted* in Activity keeps working). A workflow run that is waiting or running is never removed, and a deleted parent is kept while anything beneath it is. Files that nothing refers to after a clean-up are removed by **Settings → Storage → Tasks → Clean up unused files** (`civex store gc`); run it afterwards to get the space back.
