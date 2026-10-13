"""Devices end up agreeing whatever the order: the convergence scenario of
`civex.testing.convergence`, run here against a project in a folder. A host that
embeds civex runs the same scenario with its own app as the authority."""

from __future__ import annotations

import os
import random

import pytest

from civex.testing.convergence import act, populate, scenario

# More seeds (and a different start) on demand: CIVEX_SYNC_SEEDS=300 pytest ...
SEEDS = range(
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0")),
    int(os.environ.get("CIVEX_SYNC_FIRST_SEED", "0"))
    + int(os.environ.get("CIVEX_SYNC_SEEDS", "25")),
)


@pytest.mark.parametrize("seed", SEEDS)
def test_devices_end_up_agreeing_whatever_the_order(project, seed):
    problems = scenario(project, project("authority"), seed)
    assert not problems, f"seed {seed}:\n" + "\n".join(problems)


def test_the_random_actions_run_on_one_machine(project):
    """The scenario's actions are things a person could do; a failure here is
    the harness, not sync."""
    ctx = project("alone")
    populate(ctx)
    rng = random.Random("alone")
    for step in range(60):
        act(ctx, rng, step)
