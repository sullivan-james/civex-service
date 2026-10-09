# Your first project

A project is a folder with a `_civex/` folder inside it. Every `civex` command
works on the project it's run in (or below).

## Try the demo first

```bash
civex demo
cd civex-demo
civex serve --open
```

```text
Demo project created at ./civex-demo
  Schemas     Deployment, Detection
  Collection  amazon-survey-2024
  Records     2 deployments, 7 detections
```

It's a throwaway project with sample data, so you can click around before
setting up your own.

## Start your own

```bash
mkdir my-study && cd my-study
civex init
civex serve --open          # the app, at http://localhost:8000
```

`civex init` makes:

```text
_civex/
  config.toml     settings: database, storage volumes, sync, retention
  civex.db        the database (SQLite)
  objects/        stored files
  workflows/      workflow YAML
  plugins/        your own plugins
```

**Which database?** If Docker is running, `civex init` sets up a PostgreSQL
container for the project, and otherwise it uses SQLite. `civex init --sqlite`
always picks SQLite. You can move between them later with `civex db move`. See
[PostgreSQL](../guides/postgresql.md).

To start the app with a double-click, `civex shortcut` puts a shortcut for this
project on your Desktop.

**Next:** [Five-minute tour →](tour.md)
