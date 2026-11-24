"""What a plugin setting *is*, said in its JSON schema so a form can offer the
right control: a field picker instead of a text box, a pattern made from an
example filename instead of a regular expression.

A setting carries `{"x-civex": {"kind": ..., ...}}` (`json_schema_extra=
hint(...)` on its pydantic `Field`). Kinds:

- `field`: a field name. `of` names the setting holding the schema the field
  is on (else the record the workflow runs on); `dtypes` limits the types.
- `schema`: a schema name. `collection`: a collection name (blank: the
  record's own). `record`: a record id (blank: the record the workflow runs on).
- `pattern`: a regular expression with one capture group, matched against
  file names. `on` names the setting holding the field whose files' names it
  reads (`field`), or `files` for files given when the workflow is run;
  `date_format` names a setting it fills for a date in the name, `read_as` the
  setting saying what the value is read as (`string`, `date`, ...), and
  `keys: true` that the value is matched against records, so two names giving
  the same key is a problem.
- `date_format`: a token format (`YYYYMMDD-HHmmSS`) for a date in a name.
- `choice`: one of `choices` (a list of `{value, label}`; a choice may carry
  `feature`, the server feature it needs, and is left out where the server
  lacks it).
- `folder`: a folder on the computer civex runs on (a folder chooser).

`advanced: true` puts a setting under "More settings". `when: {setting, is}`
shows a setting only while another setting holds one of the values `is`.

The settings model as a whole may carry `{"x-civex-says": "..."}`
(`model_config = ConfigDict(json_schema_extra=says(...))`): one sentence of
what the step does, with `{setting}` and `{input}` placeholders the form fills
with what has been chosen ("Sets this record's {field} to {value}.").

A form that doesn't
know a kind shows a plain input, so a plugin may use them or not; nothing is
checked from them.
"""

from __future__ import annotations

from typing import Any


def hint(kind: str, **more: Any) -> dict[str, Any]:
    return {"x-civex": {"kind": kind, **more}}


def choices(*pairs: tuple[str, str]) -> dict[str, Any]:
    return hint("choice", choices=[{"value": v, "label": label} for v, label in pairs])


def when(
    setting: str, *values: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """`extra` (a hint) shown only while `setting` is one of `values`."""
    out = dict(extra or {"x-civex": {}})
    out["x-civex"] = {
        **out["x-civex"],
        "when": {"setting": setting, "is": list(values)},
    }
    return out


def advanced(extra: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    out = dict(extra or {"x-civex": {}})
    out["x-civex"] = {**out["x-civex"], "advanced": True, **more}
    return out


def says(sentence: str) -> dict[str, Any]:
    """What the step does, as a sentence with `{setting}`/`{input}` blanks."""
    return {"x-civex-says": sentence}
