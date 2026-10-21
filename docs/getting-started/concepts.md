# Record types, collections and records

Three ideas carry everything in civex. People new to it mix up the first and
the last, so here they are in plain words before anything else.

<span class="rt">Record type</span> &nbsp; <span class="coll">Collection</span> &nbsp; <span class="rec">Record</span>

These colours are used wherever the docs name the three.

## A blank form, a binder, a filled-in form

**A <span class="rt">record type</span> is a blank form.** When you design the form you
decide the boxes (**fields**) and what is allowed in each box (**rules**): "Depth,
a number, in metres, not below 0". You design it once. In the CLI and the API a
record type is called a *schema*; the app says *record type*.

**A <span class="rec">record</span> is one filled-in copy of that form.** Every time you
have another sample, you fill in a new copy. You don't redesign the form.

**A <span class="coll">collection</span> is the binder the filled-in forms go in.** It
says which record types may go in it, and that's all it does. One per study,
site or season, as suits you.

```mermaid
flowchart LR
    T["Record type<br/><i>blank form, designed once</i>"]:::rt -->|is the form for| R["Record<br/><i>one filled-in form</i>"]:::rec
    C["Collection<br/><i>the binder</i>"]:::coll -->|holds| R
    classDef rt fill:#dbeafe,stroke:#1e3a8a,color:#1e3a8a
    classDef coll fill:#fef3c7,stroke:#78350f,color:#78350f
    classDef rec fill:#dcfce7,stroke:#14532d,color:#14532d
```

| | How many | Looks like | Made where |
|---|---|---|---|
| <span class="rt">Record type</span> | A handful per project | *Sample*, *Site*, *Visit* | **Record types** in the sidebar, once |
| <span class="coll">Collection</span> | One per study or season | *survey-2024* | **Collections → New collection** |
| <span class="rec">Record</span> | Hundreds or thousands | *Sample 03*, *North Ridge* | Inside a collection: **New ▸ New sample** |

## Which one do I want?

Ask yourself about the thing you're about to create:

- Can you say "**a** ___"? "A sample", "a site", "a visit". That is a
  <span class="rt">record type</span>. You will have a few of them in the whole project.
- Is it "**this** ___"? "Sample 3", "the North Ridge site", "the visit on 15 March".
  That is a <span class="rec">record</span>. You will have hundreds.
- Does it have the **same boxes** as something you already have? Then you want
  a new <span class="rec">record</span> of that type, not a new type.

!!! warning "If you're making a new record type every time you add data, stop"
    You want **New ▸ New sample** inside your <span class="coll">collection</span>.
    A record type is the form, not the data. A project with one record type per
    measurement has no way to list, filter or export them together; a project with
    one *Sample* type and five hundred sample records does.

## Types that go inside other types

A record type can be designed to sit **inside** another: a *Visit* goes inside
a *Site*, a *Sample* goes inside a *Visit*. Then every sample record you add is
filed under the visit it belongs to, and can show and filter on the visit's
and the site's fields without you typing them again.

```mermaid
flowchart LR
    S["Site"]:::rt --> V["Visit"]:::rt --> P["Sample"]:::rt
    s1["North Ridge"]:::rec --> v1["2024-03-15"]:::rec --> p1["Sample 01"]:::rec
    v1 --> p2["Sample 02"]:::rec
    s1 --> v2["2024-04-02"]:::rec --> p3["Sample 01"]:::rec
    classDef rt fill:#dbeafe,stroke:#1e3a8a,color:#1e3a8a
    classDef rec fill:#dcfce7,stroke:#14532d,color:#14532d
```

The top row is the three record types, designed once. Everything below is
records. You choose the parent when you create the type (**Goes inside**), and
it can't be changed later.

## The same example everywhere

The rest of the docs use this one example, a field survey:

| Record type | Its fields | Goes inside |
|---|---|---|
| <span class="rt">Site</span> | name, location | — |
| <span class="rt">Visit</span> | visited on, team, notes | Site |
| <span class="rt">Sample</span> | number, depth (m), taken at, photo, reading | Visit |

Collection: <span class="coll">survey-2024</span>. Records look like
<span class="rec">North Ridge › 2024-03-15 › Sample 03</span>.

**Next:** [Five-minute tour →](tour.md)
