# Releasing (PyPI)

Releases of the Python package `flights` are driven by a manual GitHub
Actions workflow. There is no auto-publish on push to `main`; cutting a
release is always an explicit, one-click action.

For the TypeScript / JavaScript package (`fli` on npm), see
[`release-npm.md`](release-npm.md) — the same shape, different manifest,
different tag prefix (`fli-js-vX.Y.Z`).

## Overview

The release pipeline is two independent workflows:

| Workflow | File | Trigger |
| --- | --- | --- |
| **Release** | `.github/workflows/release.yml` | `workflow_dispatch` only |
| **Upload Python Package** | `.github/workflows/publish.yml` | `release: published`, `workflow_dispatch` |

`release.yml` is the end-to-end release pipeline: it bumps the version in
`pyproject.toml`, refreshes `uv.lock`, commits to `main`, creates an annotated
tag and GitHub Release, runs the full test matrix against the new tag, and
builds + uploads to PyPI via Trusted Publishing — all inline, no chained
workflow.

`publish.yml` is a standalone publish workflow used for:
- **Manual recovery** — if `release.yml`'s publish step ever fails, dispatch
  `publish.yml` on the failed tag (`environment: pypi`) to ship it.
- **Manual GitHub Release** — if you create a release in the UI from an
  existing tag, the `release: published` trigger picks it up and publishes.
- **TestPyPI smoke tests** — `workflow_dispatch` with `environment: testpypi`.

> **Why two workflows instead of one reusable?** PyPI's Trusted Publishing
> attestations are incompatible with reusable workflow chains
> ([pypa/gh-action-pypi-publish#166](https://github.com/pypa/gh-action-pypi-publish/issues/166)).
> When `release.yml` calls `publish.yml` via `workflow_call`, the OIDC token's
> `job_workflow_ref` points at `publish.yml` while the Sigstore cert's
> `Build Config URI` points at `release.yml`; PyPI ties both to the same
> publisher and rejects the attestation. Inlining the publish step into
> `release.yml` sidesteps this entirely.

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

* **PyPI Trusted Publishers** for the `flights` project, both bound to this
  repo and the `pypi` environment:
  * `release.yml` — used by the automated end-to-end release flow
  * `publish.yml` — used by manual recovery, `release: published`, and
    TestPyPI dispatch
  
  Configure both at
  [pypi.org/manage/project/flights/settings/publishing/](https://pypi.org/manage/project/flights/settings/publishing/).
  Set Environment name to `pypi` on both.
* **Branch protection on `main`** must permit pushes from `github-actions[bot]`.
  If protection blocks the bot, the release workflow's push will fail; switch
  the checkout step's `token:` to a PAT secret instead.
* **Workflow permissions**: `release.yml` requires `contents: write` (already
  declared at the workflow level) and `id-token: write` on the `publish`
  job for OIDC.

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
* **PyPI returns 400 "Invalid attestations supplied"** with cert URI mismatch
  — the publish job is running via a `workflow_call` chain (the original
  bug). Make sure the publish job is defined inline in `release.yml`, not
  invoked via `uses: ./.github/workflows/publish.yml`. As a one-time recovery
  for the failed tag, dispatch `publish.yml` standalone on that tag.

## Manual fallback

If `release.yml`'s publish step fails after the tag and GitHub Release have
already been created (e.g. transient PyPI outage), recover with:

1. Actions → **Upload Python Package** → Run workflow
2. **Branch dropdown**: switch to the failed tag (e.g. `vX.Y.Z`)
3. `environment`: `pypi`
4. Run

This dispatches `publish.yml` standalone and uploads the same tag's artifact.

If the entire `release.yml` workflow is broken and a release is urgent, you
can also:

1. Bump the version in `pyproject.toml` and `uv.lock` on a branch, merge to
   `main`.
2. Tag `vX.Y.Z` and push the tag.
3. Create a GitHub Release in the UI from that tag — `publish.yml`'s
   `release: published` trigger will pick it up and publish.
