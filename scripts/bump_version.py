#!/usr/bin/env python3
"""Bump the version in pyproject.toml or package.json.

Reads the current version from a project manifest and writes a new value
chosen by one of:

* ``--bump {patch,minor,major}`` — increment the corresponding semver field
* ``--explicit X.Y.Z`` — set an exact version

The manifest is selected with one of:

* ``--pyproject PATH`` — TOML file with a ``[project].version`` key
  (default: ``./pyproject.toml``)
* ``--package-json PATH`` — JSON file with a top-level ``version`` key

The optional ``--tag-prefix`` flag controls the leading characters of the
``tag=`` output line (default: ``v``); pass e.g. ``--tag-prefix fli-js-v``
when releasing the JS package.

Outputs (always to stdout, one per line, ``KEY=VALUE`` format):

* ``current=<old version>``
* ``new=<new version>``
* ``tag=<prefix><new version>``

When ``--write`` is passed, the manifest is updated in place. When
``--github-output`` is passed, the same ``KEY=VALUE`` lines are appended
to the file at ``$GITHUB_OUTPUT`` for use in GitHub Actions.

The script is intentionally dependency-free (stdlib only) so it can run in
minimal CI images without ``uv sync``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_LINE_RE = re.compile(r'(?m)^version\s*=\s*"[^"]+"')
PROJECT_TABLE_RE = re.compile(r"(?m)^\[project\]\s*$")
TABLE_HEADER_RE = re.compile(r"(?m)^\[[^\]]+\]\s*$")


def read_current_version(pyproject: Path) -> str:
    """Return the ``[project].version`` value from a TOML manifest."""
    data = tomllib.loads(pyproject.read_text())
    return data["project"]["version"]


def read_current_version_package_json(package_json: Path) -> str:
    """Return the top-level ``version`` value from a ``package.json``."""
    data = json.loads(package_json.read_text())
    version = data.get("version")
    if not isinstance(version, str):
        raise RuntimeError(f"No top-level 'version' string in {package_json}")
    return version


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


def _find_top_level_string_value_span(text: str, key: str) -> tuple[int, int] | None:
    """Find the byte span of the quoted value for a top-level JSON key.

    Walks ``text`` character-by-character, tracking object/array nesting depth
    and string literal boundaries (with backslash escapes). Returns
    ``(start, end)`` such that ``text[start:end]`` is the value's quoted string
    literal (including the surrounding quotes) when ``key`` is found at the
    top level of the root object. Returns ``None`` if no matching top-level
    key exists. Raises ``RuntimeError`` on malformed JSON (unterminated string).

    Crucially, a key with the same name nested inside an inner object — e.g.
    a dependency literally named ``"version"`` — is never matched.
    """
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            # Scan to the end of this string literal, respecting backslash escapes.
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            else:
                raise RuntimeError("unterminated JSON string literal")
            if depth == 1 and text[i + 1 : j] == key:
                # Expect ``: "..."`` immediately after; if not, this was a
                # value string rather than a key — keep scanning.
                k = j + 1
                while k < n and text[k] in " \t\n\r":
                    k += 1
                if k < n and text[k] == ":":
                    k += 1
                    while k < n and text[k] in " \t\n\r":
                        k += 1
                    if k < n and text[k] == '"':
                        v_end = k + 1
                        while v_end < n:
                            if text[v_end] == "\\" and v_end + 1 < n:
                                v_end += 2
                                continue
                            if text[v_end] == '"':
                                return (k, v_end + 1)
                            v_end += 1
                        raise RuntimeError("unterminated JSON string value")
            i = j + 1
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return None


def write_new_version_package_json(package_json: Path, new_version: str) -> None:
    """Replace the top-level ``version`` field in a ``package.json``.

    Walks the JSON to locate the *top-level* ``"version"`` key (depth-tracked
    so a nested key with the same name — e.g. inside ``dependencies`` — is
    never matched) and rewrites only its value. All other bytes of the file
    are preserved exactly, minimising lockfile churn and diff noise.
    """
    text = package_json.read_text()
    span = _find_top_level_string_value_span(text, "version")
    if span is None:
        raise RuntimeError(f"No top-level 'version' field found in {package_json}")
    start, end = span
    package_json.write_text(text[:start] + f'"{new_version}"' + text[end:])


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns a process exit code."""
    parser = argparse.ArgumentParser(
        description="Bump the version in pyproject.toml or package.json",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--pyproject",
        type=Path,
        default=None,
        help="Path to pyproject.toml (default: ./pyproject.toml when neither flag is set)",
    )
    target.add_argument(
        "--package-json",
        type=Path,
        default=None,
        help="Path to package.json",
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
        help="Write the new version to the manifest (default: print only)",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Also append KEY=VALUE lines to $GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--tag-prefix",
        default="v",
        help="Prefix for the tag= output line (default: 'v')",
    )
    args = parser.parse_args(argv)

    if args.package_json is not None:
        manifest = args.package_json
        current = read_current_version_package_json(manifest)
        writer = write_new_version_package_json
    else:
        manifest = args.pyproject if args.pyproject is not None else Path("pyproject.toml")
        current = read_current_version(manifest)
        writer = write_new_version

    new = compute_next_version(current, args.bump, args.explicit)
    tag = f"{args.tag_prefix}{new}"

    lines = [f"current={current}", f"new={new}", f"tag={tag}"]
    for line in lines:
        print(line)

    if args.write:
        writer(manifest, new)

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
