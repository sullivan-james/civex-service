# Getting started

## Installation

### Recommended: pipx

```bash
pip install pipx
pipx ensurepath        # adds civex to PATH — open a new terminal after this
```

Download the latest release wheel and install:

```bash
gh release download --repo sullivan-james/civex-service --pattern "*.whl"
pipx install "./civex-0.1.0-py3-none-any.whl[server]"
```

To upgrade, re-run `pipx install --force` with the new wheel.

### From source (development)

```bash
git clone https://github.com/sullivan-james/civex-service
cd civex-service
python -m venv venv && source venv/bin/activate
pip install -e ".[postgres,workflows,server]"
```

## Initialise a project

Navigate to your project directory and run:

```bash
civex init
```

This creates a `.civex/` directory with:

```
.civex/
  config.toml     # database URL and optional remote config
  civex.db        # SQLite database
  objects/        # content-addressed file storage
  workflows/      # YAML workflow definitions
  plugins/        # custom Python plugins
```

By default civex uses SQLite. To use PostgreSQL instead:

```bash
civex init --db postgresql://user:pass@localhost/mydb
```

## Quick start

```bash
# Define your data shape
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex schema add-field trial duration --type float
civex schema add-field trial result --type string --choices "pass,fail,inconclusive"

# Create a container for your data
civex dataset create study-2024

# Add a record (civex will prompt for each field)
civex record add --to study-2024 --schema trial

# Query records
civex record find --in study-2024 --schema trial
```

## Start the web UI

```bash
civex serve
```

Open [http://localhost:8000](http://localhost:8000). The UI lets you browse schemas, datasets, and records, upload files, run workflows, and monitor jobs — all without using the CLI.

!!! tip
    Use `civex serve --reload` during development for automatic restarts on code changes.
