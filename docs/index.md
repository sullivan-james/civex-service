# Civex

Civex is a local-first research data management tool. It gives you structured storage for your research data — typed schemas, file attachments, and automated processing workflows — without requiring a cloud service or a database administrator.

## Core concepts

| Concept | What it is |
|---|---|
| **Schema** | A template that defines the shape of your data — its field names, types, and validation rules. |
| **Collection** | A named container of records. Think of it as a project or experiment container. |
| **Record** | One row of data that conforms to a schema, stored inside a collection. |
| **Field** | A typed column on a schema. Types include text, numbers, dates, file attachments, and references to other records. |
| **Workflow** | A YAML-defined automation that runs when records are created or updated, or when triggered manually. |
| **Plugin** | A Python class that implements one step of a workflow. |

## How data flows

```
Schema ──defines──▶ Record
                      │
                      ├── stored in ──▶ Collection
                      ├── has ──────▶ Files (content-addressed objects)
                      └── triggers ──▶ Workflow jobs
```

Schemas can inherit from a parent schema. A child schema's records are linked to a parent record, allowing you to model hierarchical data (e.g. an Encounter containing many Selections, each containing many Recordings).

## Two interfaces

Everything is available via both the **CLI** and the **web UI + HTTP API**. The CLI is useful for scripting and batch operations; the UI is better for exploring and editing data interactively.

## Next steps

- [Install civex →](getting-started/install.md)
- [Create your first project →](getting-started/first-project.md)
- [Take the five-minute tour →](getting-started/tour.md)
- [Understand schemas and field types →](guides/schemas-and-fields.md)
- [Automate with workflows →](guides/workflows.md)
