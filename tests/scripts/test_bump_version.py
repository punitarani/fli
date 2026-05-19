"""Tests for ``scripts/bump_version.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "bump_version.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bump_version", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load_module()


PYPROJECT_TEMPLATE = """\
[project]
name = "flights"
version = "{version}"
description = "test"
"""


@pytest.fixture
def pyproject(tmp_path: Path) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT_TEMPLATE.format(version="0.8.5"))
    return p


class TestComputeNextVersion:
    @pytest.mark.parametrize(
        "current, bump, expected",
        [
            ("0.8.5", "patch", "0.8.6"),
            ("0.8.5", "minor", "0.9.0"),
            ("0.8.5", "major", "1.0.0"),
            ("1.2.3", "patch", "1.2.4"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("0.0.0", "patch", "0.0.1"),
            ("9.9.9", "minor", "9.10.0"),
        ],
    )
    def test_bumps(self, current, bump, expected) -> None:
        assert bump_version.compute_next_version(current, bump, None) == expected

    def test_explicit_overrides_bump(self) -> None:
        assert bump_version.compute_next_version("0.8.5", None, "1.2.3") == "1.2.3"

    @pytest.mark.parametrize("bad", ["0.9", "abc", "1.2.3.4", "v1.2.3", "1.2.3-rc1", ""])
    def test_invalid_explicit(self, bad) -> None:
        with pytest.raises(ValueError):
            bump_version.compute_next_version("0.8.5", None, bad)

    @pytest.mark.parametrize("current", ["0.9", "abc", "v1.2.3"])
    def test_invalid_current(self, current) -> None:
        with pytest.raises(ValueError):
            bump_version.compute_next_version(current, "patch", None)

    def test_unknown_bump_type(self) -> None:
        with pytest.raises(ValueError):
            bump_version.compute_next_version("0.8.5", "weird", None)


class TestReadWrite:
    def test_read_current_version(self, pyproject: Path) -> None:
        assert bump_version.read_current_version(pyproject) == "0.8.5"

    def test_write_new_version_replaces_only_project_version(self, tmp_path: Path) -> None:
        # Ensure other "version" lines (e.g. inside dep tables) are left alone.
        content = '[project]\nversion = "0.8.5"\n[tool.something]\nversion = "9.9.9"\n'
        p = tmp_path / "pyproject.toml"
        p.write_text(content)
        bump_version.write_new_version(p, "0.9.0")
        out = p.read_text()
        assert 'version = "0.9.0"' in out
        # The unrelated tool table version should remain
        assert 'version = "9.9.9"' in out
        # Only one project version line
        assert out.count('version = "0.9.0"') == 1

    def test_write_raises_when_no_version_line(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("[project]\nname = 'x'\n")
        with pytest.raises(RuntimeError):
            bump_version.write_new_version(p, "0.9.0")

    def test_write_raises_when_no_project_table(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('[tool.foo]\nversion = "1.0.0"\n')
        with pytest.raises(RuntimeError):
            bump_version.write_new_version(p, "0.9.0")

    def test_write_ignores_version_in_earlier_table(self, tmp_path: Path) -> None:
        # [tool.something] appears BEFORE [project]; its version must be left
        # untouched even though it's the first 'version = "..."' line in the file.
        content = (
            "[tool.something]\n"
            'version = "9.9.9"\n'
            "\n"
            "[project]\n"
            'name = "flights"\n'
            'version = "0.8.5"\n'
        )
        p = tmp_path / "pyproject.toml"
        p.write_text(content)
        bump_version.write_new_version(p, "0.9.0")
        out = p.read_text()
        assert 'version = "9.9.9"' in out  # tool version untouched
        assert 'version = "0.9.0"' in out  # project version bumped
        assert 'version = "0.8.5"' not in out

    def test_write_ignores_version_in_later_table(self, tmp_path: Path) -> None:
        content = (
            "[project]\n"
            'name = "flights"\n'
            'version = "0.8.5"\n'
            "\n"
            "[tool.something]\n"
            'version = "9.9.9"\n'
        )
        p = tmp_path / "pyproject.toml"
        p.write_text(content)
        bump_version.write_new_version(p, "0.9.0")
        out = p.read_text()
        assert 'version = "9.9.9"' in out
        assert 'version = "0.9.0"' in out
        assert 'version = "0.8.5"' not in out


class TestCLI:
    def _run(self, monkeypatch, args) -> int:
        monkeypatch.setattr(sys, "argv", ["bump_version.py", *args])
        return bump_version.main(args)

    def test_print_only_does_not_modify_file(self, pyproject: Path, monkeypatch, capsys) -> None:
        rc = self._run(monkeypatch, ["--pyproject", str(pyproject), "--bump", "minor"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "current=0.8.5" in out
        assert "new=0.9.0" in out
        assert "tag=v0.9.0" in out
        # File untouched
        assert bump_version.read_current_version(pyproject) == "0.8.5"

    def test_write_updates_file(self, pyproject: Path, monkeypatch) -> None:
        rc = self._run(
            monkeypatch,
            ["--pyproject", str(pyproject), "--bump", "patch", "--write"],
        )
        assert rc == 0
        assert bump_version.read_current_version(pyproject) == "0.8.6"

    def test_github_output_appends_kv_lines(
        self, pyproject: Path, tmp_path: Path, monkeypatch
    ) -> None:
        gh_out = tmp_path / "gh_output"
        gh_out.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
        rc = self._run(
            monkeypatch,
            [
                "--pyproject",
                str(pyproject),
                "--bump",
                "major",
                "--github-output",
            ],
        )
        assert rc == 0
        contents = gh_out.read_text().splitlines()
        assert "current=0.8.5" in contents
        assert "new=1.0.0" in contents
        assert "tag=v1.0.0" in contents

    def test_github_output_errors_when_env_missing(self, pyproject: Path, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        rc = self._run(
            monkeypatch,
            ["--pyproject", str(pyproject), "--bump", "patch", "--github-output"],
        )
        assert rc == 1

    def test_bump_and_explicit_are_mutually_exclusive(self, pyproject: Path, monkeypatch) -> None:
        # argparse exits with SystemExit(2) for arg errors
        with pytest.raises(SystemExit):
            self._run(
                monkeypatch,
                [
                    "--pyproject",
                    str(pyproject),
                    "--bump",
                    "patch",
                    "--explicit",
                    "1.0.0",
                ],
            )

    def test_requires_one_of_bump_or_explicit(self, pyproject: Path, monkeypatch) -> None:
        with pytest.raises(SystemExit):
            self._run(monkeypatch, ["--pyproject", str(pyproject)])
