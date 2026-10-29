"""`civex.open()`: the service layer as the Python API, in this process, with no
server running."""

from __future__ import annotations

from pathlib import Path

import pytest

import civex
from civex.domain.exceptions import ConfigError


def test_opens_the_project_in_the_current_folder(project_dir: Path):
    with civex.open() as project:
        assert project.config.project_root == project_dir


def test_finds_the_project_above_a_folder(project_dir: Path, monkeypatch):
    inside = project_dir / "raw" / "2024"
    inside.mkdir(parents=True)
    monkeypatch.chdir(Path("/"))
    with civex.open(inside) as project:
        assert project.config.project_root == project_dir
    with civex.open(str(inside)) as project:
        assert project.config.project_root == project_dir


def test_no_project_says_where_it_looked(tmp_path: Path):
    with pytest.raises(ConfigError, match=str(tmp_path)):
        civex.open(tmp_path)


def test_a_block_that_finishes_is_saved(project_dir: Path):
    with civex.open(project_dir) as project:
        project.schema_svc.create("sample")
        project.schema_svc.add_field("sample", "depth", "float")
        project.dataset_svc.create("survey")
        project.record_svc.add("survey", "sample", {"depth": 1.5})

    with civex.open(project_dir) as project:
        pages = project.record_svc.iter_find("survey", schema_name="sample")
        assert [r.data["depth"] for page in pages for r in page] == [1.5]


def test_a_block_that_raises_leaves_nothing(project_dir: Path):
    with civex.open(project_dir) as project:
        project.schema_svc.create("sample")
        project.schema_svc.add_field("sample", "depth", "float")
        project.dataset_svc.create("survey")

    with pytest.raises(RuntimeError):
        with civex.open(project_dir) as project:
            project.record_svc.add("survey", "sample", {"depth": 1.5})
            raise RuntimeError("the pipeline step failed")

    with civex.open(project_dir) as project:
        assert project.record_svc.find("survey") == []
