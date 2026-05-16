#!/usr/bin/env python3
"""Regenerate ``Formula/flights.rb`` for a given ``flights`` PyPI release.

This resolves the dependency closure of ``flights==<version>`` against PyPI,
fetches each sdist's URL and SHA-256, and writes a Homebrew formula that uses
``Language::Python::Virtualenv``. Run it after each release to refresh the
tap so ``brew install punitarani/fli/flights`` pulls the latest version.

Usage
-----

    uv run python scripts/generate_homebrew_formula.py [VERSION]

If ``VERSION`` is omitted, the version from ``pyproject.toml`` is used.

Requirements
------------

* ``uv`` on PATH (used to resolve the dependency closure).
* Network access to ``pypi.org``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
FORMULA_PATH = ROOT / "Formula" / "flights.rb"
PYPROJECT = ROOT / "pyproject.toml"


def normalize(name: str) -> str:
    """Return the PEP 503 normalized form of a distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def project_version() -> str:
    """Return the ``flights`` version declared in ``pyproject.toml``."""
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def resolve_closure(version: str) -> list[tuple[str, str]]:
    """Resolve ``flights==version`` and return ``[(name, version), ...]``."""
    out = subprocess.run(
        [
            "uv",
            "pip",
            "compile",
            "--quiet",
            "--no-header",
            "--no-annotate",
            "--python-version",
            "3.13",
            "-",
        ],
        input=f"flights=={version}\n",
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    pkgs: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" not in line:
            continue
        name, ver = line.split("==", 1)
        ver = ver.split()[0].split(";")[0].strip()
        pkgs.append((name.strip(), ver))
    return pkgs


def fetch_sdist(name: str, version: str) -> tuple[str, str]:
    """Return the ``(url, sha256)`` of the sdist for ``name==version`` on PyPI."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "fli-homebrew-gen"})
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    sdist = next((u for u in data["urls"] if u["packagetype"] == "sdist"), None)
    if sdist is None:
        raise RuntimeError(f"No sdist available for {name}=={version}")
    return sdist["url"], sdist["digests"]["sha256"]


FORMULA_TEMPLATE = """\
class Flights < Formula
  include Language::Python::Virtualenv

  desc "Programmatic access to Google Flights via the fli CLI"
  homepage "https://github.com/punitarani/fli"
  url "{url}"
  sha256 "{sha}"
  license "MIT"

  depends_on "rust" => :build
  depends_on "python@3.13"

{resources}

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Usage", shell_output("#{{bin}}/fli --help")
    assert_match "flights", shell_output("#{{bin}}/fli --help")
  end
end
"""


def build_resource_block(name: str, version: str) -> str:
    """Render a single Homebrew ``resource ... do ... end`` stanza."""
    url, sha = fetch_sdist(name, version)
    return f'  resource "{normalize(name)}" do\n    url "{url}"\n    sha256 "{sha}"\n  end'


def main(argv: list[str]) -> int:
    """Write ``Formula/flights.rb`` for the requested ``flights`` version."""
    version = argv[1] if len(argv) > 1 else project_version()
    flights_url, flights_sha = fetch_sdist("flights", version)

    closure = resolve_closure(version)
    deps = [(n, v) for n, v in closure if normalize(n) != "flights"]
    deps.sort(key=lambda nv: normalize(nv[0]))

    resources = "\n\n".join(build_resource_block(n, v) for n, v in deps)
    FORMULA_PATH.write_text(
        FORMULA_TEMPLATE.format(url=flights_url, sha=flights_sha, resources=resources)
    )
    print(f"Wrote {FORMULA_PATH.relative_to(ROOT)} for flights=={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
