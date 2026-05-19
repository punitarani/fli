# Releasing

Releases are driven by a manual GitHub Actions workflow. There is no auto-publish
on push to `main`; cutting a release is always an explicit, one-click action.

## Overview

The release pipeline is two workflows:

| Workflow | File | Trigger |
| --- | --- | --- |
| **Release** | `.github/workflows/release.yml` | `workflow_dispatch` only |
| **Upload Python Package** | `.github/workflows/publish.yml` | `release: published`, `workflow_dispatch`, `workflow_call` |

`release.yml` bumps the version in `pyproject.toml`, refreshes `uv.lock`,
commits to `main`, creates an annotated tag and GitHub Release, then calls
`publish.yml` to build and upload to PyPI via Trusted Publishing.

`publish.yml` can also be triggered independently — by publishing a GitHub
Release manually, or via `workflow_dispatch` (defaults to TestPyPI for
safe smoke tests).

## Cutting a release

1. Go to **Actions → Release → Run workflow** on `main`.
2. Choose the bump:
    * `patch` (default) — bugfixes, small changes
    * `minor` — new features, additive changes
    * `major` — breaking changes
    * `explicit` — set an exact version (also fill in the `version` input)
3. Optional: set `dry_run: true` to preview the next version and release
   notes without committing or publishing. The preview appears in the run
   summary.
4. Run again with `dry_run: false` to actually release.

The workflow will:

1. Compute the next version from `pyproject.toml`.
2. Verify the tag doesn't already exist (locally and on the remote).
3. Generate release notes from the commits in the range
   `<previous tag>..HEAD`. On the very first release with no prior tag, it
   walks back to the last manual `Bump version` commit.
4. Update `pyproject.toml` and `uv.lock`.
5. Commit `chore(release): vX.Y.Z` to `main`, tag `vX.Y.Z`, push both.
6. Create a GitHub Release with the generated notes.
7. Trigger `publish.yml` (run tests, build with `uv build`, `twine check`,
   upload to PyPI via OIDC Trusted Publishing).

## Previewing locally

Use the same script the workflow uses:

```bash
# What would a minor bump produce?
python scripts/bump_version.py --bump minor

# Show the commits that would land in the next release
git log --pretty=format:'- %s (%h)' "$(git describe --tags --abbrev=0)..HEAD"
```

`bump_version.py` only prints by default — pass `--write` to actually
modify `pyproject.toml`.

## Repository prerequisites

These need to be in place once on the GitHub side:

* **PyPI Trusted Publisher** for the `flights` project, bound to this repo
  and the `pypi` environment. `publish.yml` requests an OIDC token via
  `id-token: write` and uses `pypa/gh-action-pypi-publish`.
* **Branch protection on `main`** must permit pushes from `github-actions[bot]`.
  If protection blocks the bot, the release workflow's push will fail; switch
  the checkout step's `token:` to a PAT secret instead.
* **Workflow permissions**: `release.yml` requires `contents: write` (already
  declared at the workflow level).

## Troubleshooting

* **`Tag vX.Y.Z already exists`** — someone tagged the same version earlier
  (locally or on origin). Bump again or use `bump=explicit` with a different
  version.
* **Push to `main` rejected** — branch protection is blocking the bot. Either
  add `github-actions[bot]` to the bypass list, or wire a PAT into the
  checkout step's `token:`.
* **PyPI publish step fails with OIDC error** — the Trusted Publisher
  config on PyPI doesn't match this repo/workflow/environment. Re-check the
  project's *Publishing* settings on PyPI.
* **Release notes look wrong on first run** — the workflow walks back to the
  last commit whose subject starts with `Bump version`. If you've changed
  that convention, edit `release.yml`'s "Determine commit range" step.

## Manual fallback

If the workflow is broken and a release is urgent, you can still:

1. Bump the version in `pyproject.toml` and `uv.lock` on a branch, merge to
   `main`.
2. Tag `vX.Y.Z` and push the tag.
3. Create a GitHub Release in the UI from that tag — `publish.yml`'s
   `release: published` trigger will pick it up and publish.
