#!/usr/bin/env python3
"""Bump the version in pyproject.toml.

Reads the current `[project].version` from ``pyproject.toml`` and writes a
new value chosen by one of:

* ``--bump {patch,minor,major}`` — increment the corresponding semver field
* ``--explicit X.Y.Z`` — set an exact version

Outputs (always to stdout, one per line, ``KEY=VALUE`` format):

* ``current=<old version>``
* ``new=<new version>``
* ``tag=v<new version>``

When ``--write`` is passed, ``pyproject.toml`` is updated in place. When
``--github-output`` is passed, the same ``KEY=VALUE`` lines are appended
to the file at ``$GITHUB_OUTPUT`` for use in GitHub Actions.

The script is intentionally dependency-free (stdlib only) so it can run in
minimal CI images without ``uv sync``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import tomllib

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_LINE_RE = re.compile(r'(?m)^version\s*=\s*"[^"]+"')
PROJECT_TABLE_RE = re.compile(r"(?m)^\[project\]\s*$")
TABLE_HEADER_RE = re.compile(r"(?m)^\[[^\]]+\]\s*$")


def read_current_version(pyproject: Path) -> str:
    """Return the ``[project].version`` value from ``pyproject``."""
    data = tomllib.loads(pyproject.read_text())
    return data["project"]["version"]


def compute_next_version(current: str, bump: str | None, explicit: str | None) -> str:
    """Compute the next semver string given a current value and a bump kind.

    When ``explicit`` is set it takes precedence; otherwise ``bump`` must be
    one of ``patch``, ``minor``, or ``major``. Raises ``ValueError`` on any
    malformed input.
    """
    if explicit is not None:
        if not SEMVER_RE.match(explicit):
            raise ValueError(f"Invalid explicit version: {explicit!r}")
        return explicit

    m = SEMVER_RE.match(current)
    if not m:
        raise ValueError(f"Cannot parse current version: {current!r}")
    major, minor, patch = (int(x) for x in m.groups())

    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unknown bump type: {bump!r}")

    return f"{major}.{minor}.{patch}"


def write_new_version(pyproject: Path, new_version: str) -> None:
    """Replace the ``[project].version`` line in ``pyproject`` with ``new_version``.

    The substitution is scoped to the ``[project]`` table so a ``version`` key
    in an earlier table (e.g. ``[tool.something]``) is never touched.
    """
    text = pyproject.read_text()
    proj = PROJECT_TABLE_RE.search(text)
    if not proj:
        raise RuntimeError("No [project] table found in pyproject.toml")
    section_start = proj.end()
    next_header = TABLE_HEADER_RE.search(text, pos=section_start)
    section_end = next_header.start() if next_header else len(text)
    section = text[section_start:section_end]
    updated_section, n = VERSION_LINE_RE.subn(f'version = "{new_version}"', section, count=1)
    if n != 1:
        raise RuntimeError("Failed to locate a version line within the [project] table")
    pyproject.write_text(text[:section_start] + updated_section + text[section_end:])


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns a process exit code."""
    parser = argparse.ArgumentParser(description="Bump the version in pyproject.toml")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml (default: ./pyproject.toml)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        help="Semver field to increment",
    )
    group.add_argument(
        "--explicit",
        metavar="X.Y.Z",
        help="Set an exact version",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the new version to pyproject.toml (default: print only)",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Also append KEY=VALUE lines to $GITHUB_OUTPUT",
    )
    args = parser.parse_args(argv)

    current = read_current_version(args.pyproject)
    new = compute_next_version(current, args.bump, args.explicit)
    tag = f"v{new}"

    lines = [f"current={current}", f"new={new}", f"tag={tag}"]
    for line in lines:
        print(line)

    if args.write:
        write_new_version(args.pyproject, new)

    if args.github_output:
        gh_out = os.environ.get("GITHUB_OUTPUT")
        if not gh_out:
            print(
                "::error::--github-output requested but $GITHUB_OUTPUT is not set",
                file=sys.stderr,
            )
            return 1
        with open(gh_out, "a") as fh:
            for line in lines:
                fh.write(line + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
