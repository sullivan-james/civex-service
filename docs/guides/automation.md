# Automation

Every workflow run — whether it fired automatically from a [trigger](workflows.md#triggers) or was started manually — becomes a **job** in a queue. A job moves through `pending` → `running` → `completed`/`failed`. This guide covers inspecting and processing that queue; see [Workflows](workflows.md) for defining what runs.

## Processing pending jobs

Jobs don't run the instant they're enqueued — something has to drain the queue.

=== "CLI"
    ```bash
    # Process everything pending, then exit
    civex automation run

    # Keep polling for new jobs (default: every 5s)
    civex automation run --watch
    civex automation run --watch --interval 10
    ```

=== "Web UI"
    The **Runs** page has a **Run automation** button, which appears highlighted whenever jobs are pending. Both the CLI (`civex record add`/`update`) and the server (record and workflow API calls) already drain the queue automatically right after the change that enqueued the job, so this button is mainly useful to force a drain on demand.

## Listing and inspecting jobs

=== "CLI"
    ```bash
    civex automation jobs                    # all recent jobs
    civex automation jobs --status failed     # pending | running | completed | failed
    civex automation logs <job-id>            # captured log output for one job
    ```

=== "Web UI"
    The **Runs** page lists all jobs with a status filter. Click a row to open its detail page, which shows the same log output as `civex automation logs`, plus a step-by-step diagram of the workflow's execution.

`<job-id>` accepts any unique prefix, same as record IDs.

## Enqueueing a job manually

`civex automation enqueue` adds a job to the queue without running it immediately — useful for scripting a batch of runs that a background `civex automation run --watch` will pick up:

```bash
civex automation enqueue --workflow my-workflow --record abc123
```

There's no separate "enqueue without running" action in the web UI. On a record's page, a **Run** button sits in the header beside the pin: with one applicable workflow it is **Run &lt;name&gt;**, and with several it is **Run workflow** with a list. Clicking one enqueues and processes it in one step, and a message at the corner of the screen says it started, with **View run** to jump to the record's **Runs** tab. A workflow that needs no files starts straight away; one that takes files asks for them first, in the same drop zone used to attach files to a record. The record you're on is never asked for or shown.

## Seeing runs from anywhere

While workflows are running, the status bar at the bottom of every page says so
(the same bar that shows a file move), with **See runs** and **Stop automation**.
Runs go one at a time, so it doesn't count them running; it says how many are
waiting behind the current one and, once there are several, how far through the
batch it is, with a progress bar. It stays out of the way for an ordinary edit
whose run is over in a moment.

## Finding and repeating runs

The **Runs** page lists runs in five columns: the workflow, the record it ran on
(by its current name), what started it, the result (with what it did, or why it
failed) and when it ran and how long it took. A row opens the run. The filters
above the table narrow by **workflow**, status and trigger, and the search box
matches workflow names and error text; the filters are in the address, so a view
can be linked.

To repeat runs, tick them (the box at the top of the column ticks every run on the
page) and press **Re-run N**. All of them are queued in one go, each as a new run of
the same workflow on the same record with the same input. Any that cannot be
repeated, such as one whose record has since been deleted, are listed with the
reason, and the rest still run. The **Rows** menu under the table sets how many runs
a page shows. A run's own page links to its workflow.

## Running a workflow on many records

Tick records in any list, such as a recording's **Contains** tab or a collection's
page, and **Run workflow on N** appears in the bar above the table. It lists the
workflows that fit what is listed: those for that schema, or for any, and not
those that ask for files, since the files differ per run. Choosing one queues one
run per ticked record, in one request. The message says how many started, and
names any it could not run on and why. Over HTTP this is
`POST /workflows/{name}/run-many`. It works on the records you ticked; "select all
matching" does not offer it.

## Finding and triaging runs

The **Runs** page filters with the same chips and builder as a collection: **+ Filter**
adds conditions on the workflow, the result, what started it, the schema, when it was
queued or finished, the failure type, the error message, the failing step, the chain
depth and the record, combined with AND/OR. The filter is in the address, so a view
can be linked. Older links with `?status=failed` still open.

When runs have failed, **why they failed** groups them by workflow and error with a
count each, so a thousand failures read as the few causes they are. **Show** opens
just that group's runs; **Re-run N** repeats them once the cause is fixed. **Re-run
all N** repeats every run the current filter matches, after asking (at most 1,000 at
a time). The failed run list shows each run's own error message, cut to one line,
with the step it came from; hover for the whole message.

The bar at the bottom follows a batch: a bulk start of 50 shows as 50 at once, with
how many have succeeded and failed so far. Failures count as done, so a batch of
nothing but errors still moves. If any runs failed it links to exactly those runs.
When the batch ends with failures, a notice stays until you dismiss it. Over HTTP,
`GET /jobs` and `/jobs/count` take `filter`; `GET /jobs/filter-fields` lists the
fields, `GET /jobs/failure-groups` the groups, and `POST /jobs/rerun` takes `ids` or
a `filter`.

## Runs that finished with problems

A step can finish without having done everything: rows skipped, files that matched
no record, files left alone because two share a key. The run still completes, but
it is never shown as a plain success. It reads **completed with N problems** in
the Runs list and on the run page, whose Summary opens with what went wrong and
the files it names.

## A run's page

A run opens on three tabs: **Summary** (what started it, what it did, how it ended,
and the particulars, with a link to its workflow), **Steps** (each step's input and
output) and **Records touched**, the records it created or changed, each by its
current name. The tab is in the address, so it can be linked to.

Open a run from a record's **Runs** tab and the breadcrumb at the top runs down to
that record (collection, the records above it, then the record itself), so one click
takes you back up to the recording and to its Runs tab. Open it from the **Runs**
page and the breadcrumb leads back to that list.

## What started a run

A run records why it started. Open it on the **Runs** page to see, for a run
started by an edit, **exactly which fields changed**, from what to what, and
which of them the workflow watches (the ones in its trigger's `fields:`). Fields
that changed but aren't watched are listed too, marked *also changed*. The table
shows the field name beside the trigger. A run from before this was recorded says
so.

When a run's own save starts another run, the second one says which run and
workflow started it and how many steps deep the chain is. That is how to follow
workflows that trigger each other back to where they began. From a terminal,
`civex automation logs <job>` prints the same, and `civex automation jobs` has a
*Changed* column.

## Stopping automation, and loops

Workflows can end up triggering each other: a workflow watches a field and saves
a field that another one (or itself) watches. Civex ends a chain after 10 hops,
but you can stop it sooner.

- **Stop automation** (on the **Runs** page, and in the status bar at the bottom of the
  app whenever workflows have been busy for a couple of seconds) cancels every waiting
  run, stops the running ones before their next step, and **pauses** automation.
  While it is paused, edits don't start workflows, waiting runs aren't picked up,
  and manual runs are refused with a message. A bar says automation is paused until
  you press **Resume automation**.
- **Cancel** one run with its **×** button on the Runs page, or **Cancel run** on its
  page. A waiting run never starts; a running one stops before its next step.
  A step already in progress finishes (or hits its timeout) first, because a
  plugin can't be interrupted from outside. What a cancelled run had done is kept.

```bash
civex automation stop            # pause everything and cancel waiting and running runs
civex automation status          # paused or running, and how many runs wait or run
civex automation resume          # start again
civex automation cancel <job>    # one run
civex automation delete <job>…   # delete runs; a waiting one never starts
civex automation delete --pending  # every run still waiting
```

**Delete** runs from the Runs page by ticking them (or with a filter: **Delete
all N…**). Deleting is stronger than cancelling. A waiting run never starts, a
running one stops before its next step, and a finished one is removed with its log.
What a run already changed in records stays, and is in their history.

The pause is saved in `_civex/config.toml` (`[automation] paused = true`), so it
survives a restart and applies to the server and every terminal alike.

A workflow that watches a **file** field and saves other fields on the same
record no longer triggers itself. (The file used to look changed on every save,
because of its display name; now only a real change counts.)

## Failure counts by plugin

```bash
civex automation stats
```

Shows how many failed step executions each plugin has accumulated across all jobs — useful for spotting a consistently-broken step. There's no web UI equivalent; inspect individual failed jobs on the **Runs** page instead.
