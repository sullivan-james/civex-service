# UI token audit — researcher-facing colour, type & spacing

This documents the decisions behind the expanded `@theme` block in
`frontend/src/index.css`. It is the decision record the future colour
codemod (replacing inline `text-[#hex]` / `bg-[#hex]` usage across
components with the new tokens) is expected to follow — that codemod is
separate, larger, follow-up work and is out of scope here.

## Why move off Primer

The existing palette is lifted from GitHub Primer: blue-cast neutrals
(`#656d76`, `#818b98`, `#d0d7de` all lean blue in hue), a 12px-dominant
type scale, and Primer's tight, developer-tool density. That's tuned for
expert developers scanning dense tables all day. Civex's users are
researchers — domain experts, not software experts, often on laptops,
working in bursts rather than all-day sessions. Primer optimizes for the
wrong reader.

**Reference:** Shopify Polaris (non-technical domain experts operating a
complex system) primarily, Microsoft Fluent 2 as fallback. Not Primer,
not AWS Cloudscape — both of those assume the all-day power-user density
Civex is moving away from.

## Colour

### Warm neutral ramp

Primer's neutrals (`#656d76`, `#818b98`, `#d0d7de`, `#f6f8fa`, ...) all
have `B > G > R` — a cold, blue-grey cast. The new ramp uses `R > G > B`
(a warm stone/taupe hue), which reads as calmer and less "IDE-like" for a
research tool. This is the single biggest visual signal that Civex isn't
Primer.

### One institutional accent

Blue is the safe, credible choice for a research/data tool — it doesn't
carry the "warning" or "success" connotations that would collide with
the new status family. The new accent (`#17569e`) is deliberately a
notch deeper/less saturated than Primer's `#0969da`, so it reads as
"institutional" rather than as a copy of GitHub's brand blue.

### Status semantics as first-class tokens

`success` / `attention` / `danger` each now get a full family: base
(text/icon), `-emphasis` (solid buttons, hover states), `-subtle`
(chip/banner backgrounds), and `-muted` (translucent borders). Per the
ticket, colour is never the only signal for status in the UI — every
status usage must still pair the token with an icon and a word; that's
an implementation rule for the codemod, not something CSS can enforce.

### Roles that were missing

- **Attention/warning family** — previously the "display field" chip
  hardcoded `#fff8c5` / `#9a6700` / `#d4a72c55` inline with no token at
  all. Now `--color-attention`, `--color-attention-emphasis`,
  `--color-attention-subtle`, `--color-attention-muted`.
- **`success-subtle`** — existed only as inline hex (`#dafbe1`), never a
  token. Now `--color-success-subtle` (+ `-subtle-hover` for the chip
  hover state, `-muted` for translucent borders).
- **`border-strong`** — didn't exist; every border use fell back to the
  same `#d0d7de` regardless of emphasis. Now `--color-border-strong`.
- **Overlay scrim** — modal backdrops used `bg-black/40` in five places
  and `bg-black/50` in two, arbitrarily. Now one
  `--color-overlay-scrim` token.
- **Dark-header set** — the top nav bar's five hardcoded darks
  (`#24292f`, `#2d333b`, `#444c56`, `#adbac7`, `#e6edf3`) are now named
  tokens (`--color-nav-bg`, `--color-nav-surface`, `--color-nav-border`,
  `--color-nav-fg-muted`, `--color-nav-fg`), plus two more the header
  family needed once it was actually named: `--color-nav-surface-hover`
  (`#373e47`, already hardcoded on hover states) and
  `--color-nav-surface-strong` (`#1c2128`, the dark `<pre>` log block on
  the job detail page — same family, darkest step).

### A bug this audit surfaced

`#adbac7` is GitHub's _dark-mode_ muted-foreground colour. In this
codebase it's used correctly in the nav header (which is permanently
dark chrome) — but it's also pasted as help/placeholder text colour on
plain white form backgrounds in `AiPanel.tsx` and `SettingsPane.tsx`,
where it under-contrasts. The token set fixes this by construction:
`--color-nav-fg-muted` is scoped to the dark nav/surfaces only; light-surface
secondary text now has nowhere to go but `--color-fg-subtle`. The codemod
should route the `AiPanel`/`SettingsPane` instances to `fg-subtle`, not
`nav-fg-muted`.

### Full mapping — every hex value currently in use

| Old value(s)                                     | New token                                                    | Notes                                                                                                                                                                                        |
| ------------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `#1f2328`, `#24292f` (as text colour)            | `--color-fg`                                                 | two near-identical near-blacks used interchangeably for primary text; consolidated to one                                                                                                    |
| `#656d76`                                        | `--color-fg-muted`                                           |                                                                                                                                                                                              |
| `#818b98`, `#8c959f`                             | `--color-fg-subtle`                                          | near-duplicate mid-greys, consolidated                                                                                                                                                       |
| `#ffffff` (as text colour)                       | `--color-fg-on-emphasis`                                     |                                                                                                                                                                                              |
| `#f6f8fa`                                        | `--color-canvas-subtle`                                      |                                                                                                                                                                                              |
| `#eff2f5`                                        | `--color-canvas-inset`                                       |                                                                                                                                                                                              |
| `#ffffff` (as background)                        | `--color-canvas`                                             |                                                                                                                                                                                              |
| `#d0d7de`                                        | `--color-border`                                             |                                                                                                                                                                                              |
| `#d8dee4`, `#eaeef2`                             | `--color-border-muted`                                       | consolidated duplicates                                                                                                                                                                      |
| _(none — new)_                                   | `--color-border-strong`                                      | new role, ticket-requested                                                                                                                                                                   |
| `#0969da`, `rgba(31,35,40,0.15)` (button border) | `--color-accent`                                             | the rgba border on the primary button is retired in favour of the accent family                                                                                                              |
| `#0860ca`                                        | `--color-accent-emphasis`                                    | hover/pressed state on accent buttons                                                                                                                                                        |
| `#ddf4ff`, `#f0f6ff`, `#dbeafe`                  | `--color-accent-subtle`                                      | three near-identical light-blue tints, consolidated                                                                                                                                          |
| `#b6d4fb`                                        | `--color-accent-subtle-border`                               |                                                                                                                                                                                              |
| `#54aeff`, `#54aeff66`, `#0969da55`              | `--color-accent-muted`                                       |                                                                                                                                                                                              |
| `#1a7f37`                                        | `--color-success`                                            |                                                                                                                                                                                              |
| `#1f883d`, `#3fb950`                             | `--color-success-emphasis`                                   | `#1f883d` (solid button) and `#3fb950` (bright status text on the dark nav/AI panel) served the same "emphasis" role at different luminance; folded into one token, light/dark values differ |
| `#dafbe1`                                        | `--color-success-subtle`                                     |                                                                                                                                                                                              |
| `#aceebb`                                        | `--color-success-subtle-hover`                               |                                                                                                                                                                                              |
| `#4ac26b55`, `#4ac26b66`                         | `--color-success-muted`                                      |                                                                                                                                                                                              |
| `#9a6700`                                        | `--color-attention`                                          |                                                                                                                                                                                              |
| `#7d5700`                                        | `--color-attention-emphasis`                                 |                                                                                                                                                                                              |
| `#fff8c5`                                        | `--color-attention-subtle`                                   |                                                                                                                                                                                              |
| `#d4a72c`, `#d4a72c55`                           | `--color-attention-muted`                                    |                                                                                                                                                                                              |
| `#d1242f`, `#cf222e`, `#b91c1c`, `#a40e26`       | `--color-danger` / `--color-danger-emphasis`                 | four near-duplicate reds used inconsistently for the same "error" role; `#d1242f`→`danger`, `#a40e26`→`danger-emphasis`, `#cf222e`/`#b91c1c` retired as redundant                            |
| `#ffebe9`                                        | `--color-danger-subtle`                                      |                                                                                                                                                                                              |
| `#ffd7d5`, `#fd8c73`                             | `--color-danger-subtle-border`                               |                                                                                                                                                                                              |
| `#d1242f33`, `#ff8182`, `#ff818255`, `#f85149`   | `--color-danger-muted` / dark-mode `--color-danger-emphasis` | `#f85149`/`#ff8182` are GitHub's dark-mode bright reds — now covered by the dark media-query values instead of a separate hardcoded token                                                    |
| `#818b9833`                                      | `--color-neutral-subtle`                                     | the "default" (status-free) badge chip                                                                                                                                                       |
| _(none — new)_                                   | `--color-neutral-muted`                                      | stronger neutral chip variant, for consistency with the other families                                                                                                                       |
| `bg-black/40`, `bg-black/50`                     | `--color-overlay-scrim`                                      |                                                                                                                                                                                              |
| `#24292f` (header bg)                            | `--color-nav-bg`                                             |                                                                                                                                                                                              |
| `#2d333b`                                        | `--color-nav-surface`                                        |                                                                                                                                                                                              |
| `#373e47`                                        | `--color-nav-surface-hover`                                  |                                                                                                                                                                                              |
| `#1c2128`                                        | `--color-nav-surface-strong`                                 |                                                                                                                                                                                              |
| `#444c56`                                        | `--color-nav-border`                                         |                                                                                                                                                                                              |
| `#e6edf3`, `#f0f6fc`                             | `--color-nav-fg`                                             | two near-identical bright near-whites, consolidated                                                                                                                                          |
| `#adbac7`, `#848d97`                             | `--color-nav-fg-muted`                                       | see "a bug this audit surfaced" above — only valid on dark nav/surface backgrounds going forward                                                                                             |

Every one of the 52 distinct hex values found in `frontend/src/` (via
`grep -rEho '#[0-9a-fA-F]{3,8}\b' src/ | sort -u`) is accounted for above,
either mapped to a token or explicitly retired as a duplicate of another
mapped value.

## Type

- **Retire 12px as a body size.** `text-xs` (247 uses, the single
  most-used size in the app) is now 13px, not 12px — and 13px is the
  _floor_: nothing in the new scale goes smaller.
- **15px body** — `text-base` moves from Tailwind's default 16px down to
  15px (Polaris/Fluent both run body copy at 15px for this kind of
  dense-but-approachable UI).
- **14px table cells** — `text-sm`, unchanged from Tailwind's default,
  now used deliberately for tabular/grid content rather than as a
  catch-all secondary size.
- **`text-[9px]` / `text-[10px]` / `text-[11px]` one-offs (29 uses
  across the codebase) are deleted by policy** — there is no token below
  13px, so any arbitrary sub-13px value introduced going forward should
  be flagged in review. Actually removing the 29 existing call sites is
  part of the follow-up codemod, not this ticket.

## Spacing / sizing

- **4/8/12/16/24/32 only.** Tailwind's default spacing unit
  (`--spacing: 0.25rem` = 4px) already produces exactly these values at
  `p-1`/`p-2`/`p-3`/`p-4`/`p-6`/`p-8` — no token change was needed, this
  is a usage-discipline decision: the scale's other steps (`p-5`, `p-7`,
  `p-10`, ...) and arbitrary `p-[...]` values are off-scale and should be
  flagged in review going forward.
- **Control heights** — 32px minimum, 36–40px for primary actions.
  Reference tokens `--control-height-sm/md/lg` (32/36/40px) are defined
  for components that need the value directly; `h-8`/`h-9`/`h-10` already
  resolve to the same pixel values via the spacing unit above, so either
  is fine.
- **Radius** — Tailwind's default `--radius-md` (6px) and `--radius-lg`
  (8px) already match the decided controls/surfaces split, so no token
  override was needed. The usage rule: `rounded-md` for controls,
  `rounded-lg` for surfaces, `rounded-full` for badges only. Bare
  `rounded` (`--radius-sm`, 4px) is retired.

## Dark mode

Tokens have light and dark values (see the `@media
(prefers-color-scheme: dark)` block in `index.css`), satisfying the
"light and dark values defined for each token" acceptance criterion. The
app has no dark-mode toggle today — these values activate automatically
under OS dark mode via the media query. Building a manual toggle
(persisted preference, `.dark` class wiring) is future work; the token
_values_ are decided now so that work doesn't block on design.

The dark-header (`--color-nav-*`) tokens are intentionally excluded from
the dark-mode override — the header is fixed dark chrome regardless of
the rest of the app's theme, both today and in the target design.
