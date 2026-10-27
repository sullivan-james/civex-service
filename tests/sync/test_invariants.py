"""However devices interleave changes to the project's structure and its records,
what they all end up agreeing on still makes sense: the invariants scenario of
`civex.testing.invariants`, run here against a project in a folder. A host that
embeds civex runs the same scenario with its own app as the authority."""

from __future__ import annotations

import os
import random

import pytest

from civex.testing.invariants import act, broken_rules, populate, scenario

SEEDS = range(
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0")),
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0"))
    + int(os.environ.get("CIVEX_SYNC_SEEDS", "25")),
)


# The real "a collection only holds records of its listed schemas" rule, which
# the rest of the suite switches off (tests/conftest.py).


@pytest.mark.parametrize("seed", SEEDS)
def test_what_devices_agree_on_is_a_project_one_machine_could_hold(project, seed):
    problems = scenario(project, project("authority"), seed)
    assert not problems, f"seed {seed}:\n" + "\n".join(problems[:30])


def test_the_rules_hold_for_a_project_made_on_one_machine(project):
    """The checker itself: one machine, every action, no sync. A rule broken here
    is a checker that is wrong, not sync."""
    ctx = project("alone")
    populate(ctx)
    rng = random.Random("alone")
    for step in range(200):
        act(ctx, rng, step)
    assert broken_rules(ctx) == []
