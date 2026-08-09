# Researcher-facing vocabulary

This is the agreed glossary for CIVEX-259: which implementer-facing terms
get replaced with researcher-facing ones in the **web UI**, and which stay.
CIVEX-260 applies it mechanically to `frontend/src`; CIVEX-261 separately
collapses the 13 backend field types into 7 UI concepts (referenced below
where it overlaps).

Scope, per the ticket: presentation layer only. API routes, database
columns, Python identifiers, and CLI flag/command names are untouched by
this decision — see [Scope: what this does and doesn't cover](#scope-what-this-does-and-doesnt-cover).

## Glossary

| Current term | Decision | Replacement |
|---|---|---|
| Schema | **Rename** | Record type |
| Field restrictions | **Rename** | Rules |
| Plugin (the type of thing a step runs) | **Rename** | Step type |
| Container plugin / "Tier 2" | **Rename** (UI copy only) | Custom step type |
| Display fields | **Rename** | Label fields |
| `reference` (field type) | **Rename** | Link to another record |
| `file_list` (field type) | **Fold in** — no standalone term | Becomes "File" + an "Allow more than one" modifier (CIVEX-261) |
| Collection | **Keep as is** | Collection |
| Record | **Keep as is** | Record |
| Workflow | **Keep as is** | Workflow |
| Run / Job | **Keep as is** | Run |
| Step | **Keep as is** | Step |
| Executor | **Keep as is** — not user-visible | n/a |
| Topological sort | **Keep as is** — not user-visible | n/a |
| `__input__` | **Keep as is** — config-file token, not UI copy | n/a |

## Term-by-term rationale

### Schema → Record type

A database term with no researcher meaning. "Record type" says exactly
what it does — it's the type of the records stored in a collection — and
reads naturally in context ("New record type", "Parent record type").
Matches the ticket's starting proposal.

### Field restrictions → Rules

"Restrictions" is accurate but bureaucratic. "Rules" is shorter and just
as precise for a section that lists min/max, choices, length limits, and
file-size/type limits — it doesn't need to explain *what kind* of rule,
the values underneath already do that (e.g. "min 0 · max 100").
Rejected "What's allowed" (the ticket's other candidate): it's vaguer than
"Rules" for no benefit, and the constraint is explicit that vague-but-cute
isn't the goal.

### Plugin → Step type (not "Action")

"Plugin" is pure implementer vocabulary. The ticket proposed "Step type /
Action" as alternatives — **Step type is the correct one, not Action**:
`frontend/src/components/ui/DataTable.tsx` already renders a row-level
"Actions" column (edit/delete/etc.) on nearly every table in the app.
Reusing "Action" for what a plugin does would collide with that existing,
unrelated meaning on the same screens (e.g. the workflow steps table would
have both an "Actions" column for row operations and a step's "Action"
for what it runs). "Step type" avoids the collision and is more precise
anyway: a **step** is the configured instance inside one workflow; its
**step type** is which plugin implementation it runs. This also gives a
clean name for the plugin *library* view ("Step types" instead of
"Plugins").

### Container plugin / "Tier 2" → Custom step type

Only one user-visible string currently uses "Tier" language
(`WorkflowsPage.tsx:913`, "Tier 2 plugins — Dockerfile + source tree...").
"Tier 1/Tier 2" is an internal dispatch-mechanism distinction (subprocess
vs. container) that a researcher has no reason to know exists — what they
need to know is that this is a step type they (or someone on their team)
built themselves, as opposed to one that shipped with civex. "Custom step
type" says that directly. The underlying mechanism can still be explained
in secondary help text without leading with "Tier 2" or "Dockerfile" (e.g.
"runs in its own container, built from source you provide").

Note for CIVEX-260: the plugin/container-plugin **authoring** surfaces
(`PluginEditor.tsx`, `ContainerPluginEditor.tsx` — uploading a `.py` file
or wiring up a container build) are inherently developer-facing screens.
CIVEX-260's own acceptance criteria carve out "an explicitly-labelled
Advanced area" for retired terms — these editors are the natural fit for
that carve-out if fully rewording them adds more confusion than it
removes for the (rare, technical) users who touch them. The glossary term
for the everyday step-picker UI is still "Step type" either way.

### Job / Run — keep as already decided

The ticket cites Jobs→Runs as the precedent this story extends, then its
own candidate table proposes replacing it again ("Automation history /
Activity"). Not revisiting it: "Run" already shipped
(`frontend/src/pages/JobsPage.tsx`, route `/runs`, legacy `/jobs` redirect
in `App.tsx`), and the research for this ticket found zero remaining
user-visible occurrences of "Job" in the frontend. Reopening a
already-shipped, already-precedent-setting rename would be churn, not
progress.

### Workflow — keep as is (reject "Automation")

The ticket's own problem list — *schema, restrictions, plugin, Tier 2
container plugin, job, step, executor, topological sort, `file_list`,
`reference`, `__input__`* — doesn't include "workflow"; only the separate
candidates table proposes replacing it. Keeping it:

- "Workflow" is standard non-technical language for a research audience
  (lab workflow, protocol) — it isn't implementer jargon the way "plugin"
  or "executor" are.
- It's already paired with the shipped "Run" (a workflow *has* runs) —
  the same "Workflow" + "run" pairing used by GitHub Actions, a pattern
  many technical researchers already recognize. Switching to "Automation"
  either breaks that pairing or forces "Automation" + "Automation run",
  which is more words for the same idea.
- "Automation" implies unattended, hands-off execution. Several workflows
  here are manually triggered with a review step — calling that
  "automation" is less accurate, not more, which cuts against the "never
  vague" constraint.

### Step — keep as is

Listed as jargon in the ticket description, but on inspection the
rendered UI only ever uses it in its plain-English sense — "a step in a
workflow" — never in the executor-internals sense (`step_id.output_name`
resolution, which never reaches the UI; confirmed zero occurrences of
"executor" or "topological sort" in `frontend/src`). There's no clearer
plain-language substitute for "one action in an ordered sequence"; "Step"
already reads naturally next to "Workflow" and "Step type" (see above).

### Display fields → Label fields

The existing tooltip already describes the concept in plain language —
*"included in the record's natural name"* — so the UI has effectively
already agreed on "name"/"label" as the right frame; "Display field" is
the one piece of jargon left over. "Label fields" (plural, since more
than one field can compose it, as the existing `#1`/`#2` ordinal badge
shows) is shorter than the ticket's candidate "Record label" and fits the
existing per-field badge/aria-label copy better ("Add to label fields",
"Move earlier in label order").

### `reference` → Link to another record

Matches the ticket's candidate, and it's already the exact phrase used in
`docs/guides/files.md`'s field-type table — adopting it in the UI closes
an existing UI/docs mismatch rather than opening a new one. Also matches
CIVEX-261's field-type collapse table, which uses the identical phrase.

### `file_list` — no standalone term

Per CIVEX-261, `file_list` (and `reference_list`) stop being visible field
types at all — they become "File" / "Link to another record" plus an
"Allow more than one" modifier. There's nothing for this glossary to name
independently; the decision here is just to confirm no UI copy should say
"file_list" once CIVEX-261 lands (currently it's shown raw — an
`<option>{t}</option>` and a `<Badge>{field.type}</Badge>` in
`FieldForm.tsx` / `SchemaDetailPage.tsx` — matching the "never left
unhumanized" gap that ticket exists to close).

### Executor, topological sort, `__input__` — not user-visible, no action

- **Executor**: appears only in code comments and CLI internals, never in
  rendered UI or public docs. No UI decision needed.
- **Topological sort**: does not appear in the frontend, in any public
  (built) doc page, or in user-facing CLI help text — confirmed by
  reading the CLI source: the one hit that looked user-facing on a first
  pass (`cli/dump.py:16`) is a docstring on a private helper
  (`_sort_schemas`), not a Typer command, so it never renders as `--help`
  output. The only places the phrase survives are internal code
  (`workflows/executor.py`) and `docs/contributing/architecture.md`,
  which is maintainer-only and excluded from the built site
  (`exclude_docs:` in `mkdocs.yml`). Already correctly hidden from
  researchers; nothing to change.
- **`__input__`**: a magic key in hand-authored workflow YAML files
  (`_civex/workflows/*.yaml`) and the CLI help text that explains it. This
  is a stable on-disk config format, not UI copy — renaming it is a
  breaking change to every existing workflow file, which is a different
  (and much bigger) decision than this presentation-layer glossary is
  scoped to make. Left as is. The prose *explaining* it in CLI help/docs
  should keep describing it in plain language ("the inputs you provide
  when starting a run manually") rather than assuming the reader already
  knows `__input__` is special.

## Scope: what this does and doesn't cover

Per the ticket's constraint, this glossary is presentation-layer only:

- **In scope**: web UI copy (CIVEX-260 applies it).
- **Out of scope**: API routes, query keys, TypeScript types/props, file
  names, database columns, and all Python identifiers under `src/civex/`
  — none of these change.
- **CLI**: deliberately not addressed by this decision. `civex schema`,
  `civex plugin`, `civex automation ... jobs`, `--min/--max/--choices`
  etc. keep their current names for now. Renaming them is a much bigger,
  potentially-breaking decision (existing scripts and CI pipelines call
  these by name) that deserves its own ticket rather than being folded
  into a UI-copy glossary — see follow-up below.

## Follow-up work needed

The ticket's acceptance criteria ask for docs impact to be assessed and
captured. This agent cannot file Jira tickets directly (see run
constraints), so the recommendations are written down here for whoever
triages next:

1. **Docs pass for `docs/index.md`'s "Core concepts" table and the
   `docs/guides/*` prose.** These already lag behind the *shipped* UI, not
   just this new glossary: `docs/index.md:23` still says "Workflow jobs"
   even though the UI has said "Runs" since the earlier Datasets→Collections
   /Jobs→Runs pass. Once CIVEX-260 lands, the docs will additionally
   disagree on Schema/Plugin/reference terminology. Recommend a follow-up
   doc-content ticket scoped to `docs/index.md`, `docs/guides/workflows.md`,
   `docs/guides/schemas-and-fields.md`, and `docs/guides/automation.md`.
2. **A separate decision on whether the CLI adopts this vocabulary.** The
   CLI already has one unresolved half-rename from the *previous* pass:
   the `civex collection` command group (named `collection` in
   `main.py`) still prints "dataset" throughout its own help text and
   output (e.g. `record.py`'s `--to` help says "Dataset to add the record
   to", `resolve.py` prints `"dataset ..."`). Any CLI vocabulary work
   should fix that pre-existing drift at the same time, and needs its own
   backwards-compatibility plan (aliases vs. hard rename) since CLI
   command/flag names are scripted against, unlike UI copy.
3. **`docs/reference/plugins/*` and `docs/reference/cli/*` are generated**
   (see `CLAUDE.md` § Documentation) straight from CLI help text and
   plugin registry metadata — so item 2 (if actioned) automatically
   regenerates those pages once the CLI's own strings change. No separate
   doc-generation work is needed beyond that.
