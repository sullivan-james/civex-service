# Deleting & restoring data

Deleting a schema, collection or record in civex is reversible. A delete
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
    civex collection delete study-2024
    civex record delete <record-id>
    ```

=== "Web UI"
    **Delete** on a schema, collection or record's detail page.

## Cascades

Deleting a **schema** also soft-deletes every record typed by it, across
every collection — a record type never leaves its own records behind.
Records of a *different* schema that reference one of those records as a
parent are left alone; they stay visible, pointing at a hidden parent,
until it's restored.

Deleting a **collection** also soft-deletes every record in it.

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
    civex collection restore study-2024
    civex record restore <record-id>
    ```

=== "Web UI"
    Go to **Recently Deleted** in the sidebar, find the item, and click **Restore**.

Restoring a schema or collection also restores the records that were
cascade-deleted with it; restoring a record also restores its cascade-deleted
children. If any of those records had already been deleted individually
*before* the parent was deleted, restoring the parent restores them too —
restore mirrors the cascade at delete time rather than tracking each delete
as a separately-undoable batch.

## Retention and permanent deletion

Soft-deleted items become eligible for permanent deletion after a
configurable number of days (`purge_after_days`, default 30 — see
**Settings → Recently Deleted** or `[retention]` in `_civex/config.toml`).
Reaching that age doesn't delete anything by itself; permanent deletion is
always a separate, explicit action:

=== "CLI"
    ```bash
    civex schema purge trial              # must already be deleted
    civex collection purge study-2024
    civex record purge <record-id>
    civex trash purge-expired             # purge everything past the retention window
    ```

=== "Web UI"
    **Delete permanently** on an item in Recently Deleted.

Purging is irreversible: it removes the row (and, for a schema or
collection, everything cascade-deleted with it) for good.
