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

There's no separate "enqueue without running" action in the web UI — running a workflow from a record's detail page enqueues and processes it in one step.

## Failure counts by plugin

```bash
civex automation stats
```

Shows how many failed step executions each plugin has accumulated across all jobs — useful for spotting a consistently-broken step. There's no web UI equivalent; inspect individual failed jobs on the **Runs** page instead.
