# Automation

Every time a [workflow](workflows.md) runs, by a trigger or by hand, it is a
**run** (a *job* in the CLI). Runs queue and go one at a time:
`pending → running → completed | failed | cancelled`.

## Runs happen by themselves

Record changes made in the app, over the API or with `civex record add/update`
start their runs straight away. Two cases need a nudge:

```bash
civex automation run              # run whatever is waiting, then exit
civex automation run --watch      # keep running new ones (every 5 s; --interval)
civex automation enqueue --workflow my-workflow --record 2d69dc46   # queue without running
```

The **Runs** page's **Run automation** button does the same as
`civex automation run`.

## Seeing runs

```bash
civex automation jobs --status failed     # pending|running|completed|failed|cancelled
civex automation logs <job id>            # one run's log, and what started it
civex automation stats                    # failures per plugin
```

```text
ID         Workflow      Schema     Record             Trigger  Changed  Status
1adcfb22…  extract-sta…  recording  Take 01 bfcdc007…  manual   —        failed
```

**The Runs page** lists runs with their workflow, record, trigger, result and
time. **+ Filter** builds conditions on workflow, status, trigger, schema, time,
failure type, error message, failing step and chain depth, like a record
filter. It's all in the address, so a filtered list can be linked.

**A run's page** has three tabs: **Summary** (what started it, what it did, how
it ended), **Steps** (each step's input and output) and **Records touched**.
Opened from a record's **Runs** tab, its breadcrumb leads back to that record.

- **What started it:** for an edit, exactly which fields changed, from what to
  what, and which of them the workflow watches. For a run started by another
  run, which one, and how deep the chain is.
- **Completed with N problems:** a run that finished but skipped rows, or left
  files that matched no record (or matched ambiguously), is never shown as a plain
  success. The Summary opens with what went wrong.

The status bar at the bottom of every page shows runs in progress (and how many
are waiting), a progress bar for a batch, and a notice if a batch ended with
failures.

## Failures: triage and re-run

When runs fail, **why they failed** on the Runs page groups them by workflow and
error, so a thousand failures read as the few causes they are. **Show** lists a
group, and **Re-run N** repeats it once the cause is fixed.

Tick runs and **Re-run N** to repeat them (same workflow, record and input), or
**Re-run all N** for everything the filter matches (up to 1,000). Runs that can't
be repeated, for example because their record was deleted, are listed with the
reason.

Over HTTP: `GET /api/jobs?filter=…`, `GET /api/jobs/failure-groups`,
`POST /api/jobs/rerun` (`ids` or `filter`), `POST /api/workflows/{name}/run-many`.

## Stopping automation

Workflows can trigger each other, or themselves. civex ends a chain after 10
hops, but you can stop everything sooner:

```bash
civex automation stop            # pause, and cancel waiting and running runs
civex automation status          # paused or running, and how many wait
civex automation resume
civex automation cancel <job>    # one run
civex automation delete <job>…   # remove runs (a waiting one never starts)
civex automation delete --pending
```

- **Stop** pauses automation: edits start no runs, waiting runs aren't picked
  up, and manual runs are refused, until **Resume**. The pause is saved in
  `config.toml` (`[automation] paused = true`), so it holds across restarts and
  for every terminal.
- A running run stops **before its next step**. A step already running finishes
  first, because a plugin can't be interrupted.
- Cancelling or deleting a run keeps whatever it already changed in records,
  which is in their history.

In the app: **Stop automation** on the Runs page and in the status bar, and a
run's **×** or **Cancel run**.
