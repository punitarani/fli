# Releasing fli-js to npm

Releases of the TypeScript / JavaScript package `fli` on
[npmjs.com](https://www.npmjs.com/package/fli) are driven by a manual
GitHub Actions workflow. There is no auto-publish on push to `main`;
cutting a release is always an explicit, one-click action — same shape
as the Python release flow, but on its own schedule.

## Overview

The npm release pipeline is two workflows, parallel to the PyPI pair:

| Workflow | File | Trigger |
| --- | --- | --- |
| **Release npm** | `.github/workflows/release-npm.yml` | `workflow_dispatch` only |
| **Upload npm Package** | `.github/workflows/publish-npm.yml` | `release: published` (fli-js-v* tags), `workflow_dispatch`, `workflow_call` |

`release-npm.yml` bumps the version in `fli-js/package.json`, refreshes
`fli-js/bun.lock`, commits to `main`, creates an annotated tag
`fli-js-vX.Y.Z` and a GitHub Release, then calls `publish-npm.yml` to
build the package and upload it to npm with provenance attestation.

`publish-npm.yml` can also be triggered independently — by publishing a
GitHub Release with a `fli-js-v*` tag, or via `workflow_dispatch`
(defaults to a dry-run pack-only build).

The Python (`flights`) and JavaScript (`fli`) packages are versioned
**independently**. Python releases use the tag prefix `v` (e.g.
`v0.9.0`); JS releases use `fli-js-v` (e.g. `fli-js-v0.2.0`). The two
publish workflows filter on the tag prefix so a Python release does not
trigger an npm publish (and vice versa).

## Cutting a release

1. Go to **Actions → Release npm → Run workflow** on `main`.
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

1. Compute the next version from `fli-js/package.json`.
2. Verify the tag `fli-js-vX.Y.Z` doesn't already exist
   (locally and on the remote).
3. Generate release notes from the commits in the range
   `<previous fli-js tag>..HEAD`, filtered to paths
   `fli-js/` and `data/`.
4. Update `fli-js/package.json` and `fli-js/bun.lock`.
5. Commit `chore(release): fli-js-vX.Y.Z` to `main`, tag
   `fli-js-vX.Y.Z`, push both.
6. Create a GitHub Release with the generated notes.
7. Trigger `publish-npm.yml`:
   * Run the existing `fli-js.yml` test pipeline
     (format / lint / typecheck / tests).
   * Re-install with `bun install --frozen-lockfile`.
   * Verify generated enums are in sync with `data/`.
   * Build via `bun run build` (`tsc -p tsconfig.build.json`).
   * Sanity-check the build output and `npm pack --dry-run` contents.
   * Pack the tarball, upload it as an artifact.
   * Publish to npm with `npm publish --provenance --access public`.

## Previewing locally

```bash
# What would a minor bump produce?
python scripts/bump_version.py \
  --package-json fli-js/package.json \
  --bump minor \
  --tag-prefix fli-js-v

# Show the commits that would land in the next release
git log --pretty=format:'- %s (%h)' \
  "$(git tag --list 'fli-js-v*' --sort=-v:refname | head -n1)..HEAD" \
  -- fli-js data

# Validate the build end-to-end
cd fli-js
bun install --frozen-lockfile
bun run build
npm pack --dry-run
```

`bump_version.py` only prints by default — pass `--write` to actually
modify `fli-js/package.json`.

## Repository prerequisites

These need to be in place once on the GitHub side:

* **`NPM_TOKEN` secret** — an npm automation token bound to a user with
  publish rights on the `fli` package. Create one at
  <https://www.npmjs.com/settings/~/tokens> (type *Automation*) and add
  it under **Settings → Secrets and variables → Actions → New repository
  secret**.
* **`npm` GitHub environment** — `publish-npm.yml` references
  `environment: npm`. Create it under **Settings → Environments** if you
  want manual approvals or environment-scoped secrets. Otherwise the
  default environment-less behaviour applies.
* **Provenance** — `publish-npm.yml` requests `id-token: write` and runs
  `npm publish --provenance`. No extra config required; the action runs
  on a public repo with publicly-readable workflow logs, which is what
  npm provenance attestation requires.
* **Branch protection on `main`** must permit pushes from
  `github-actions[bot]`. If protection blocks the bot, the release
  workflow's push will fail; switch the checkout step's `token:` to a
  PAT secret instead.

## Troubleshooting

* **`Tag fli-js-vX.Y.Z already exists`** — someone tagged the same
  version earlier (locally or on origin). Bump again or use
  `bump=explicit` with a different version.
* **Push to `main` rejected** — branch protection is blocking the bot.
  Either add `github-actions[bot]` to the bypass list, or wire a PAT
  into the checkout step's `token:`.
* **`npm publish` fails with `EOTP` or 401** — the `NPM_TOKEN` is
  expired, has the wrong scope, or doesn't have publish rights on the
  package. Re-issue an Automation token from npm and update the secret.
* **`npm publish` fails with provenance error** — the workflow must run
  on a public repo and the runner must be an ephemeral GitHub-hosted
  runner. Provenance is unavailable on self-hosted runners.
* **`Generated enums are out of date`** — `bun run generate:enums`
  produced a diff. Regenerate locally, commit, and re-run the release.

## Manual fallback

If the workflow is broken and a release is urgent, you can still:

1. Bump the version in `fli-js/package.json` and `fli-js/bun.lock` on a
   branch, merge to `main`.
2. Tag `fli-js-vX.Y.Z` and push the tag.
3. Create a GitHub Release in the UI from that tag — `publish-npm.yml`'s
   `release: published` trigger will pick it up and publish.

If even that fails, publishing locally as a last resort:

```bash
cd fli-js
bun install --frozen-lockfile
bun run build
npm publish --provenance --access public
```

(requires `npm login` first, and skips the GitHub Release / provenance
attestation since the build didn't happen in CI.)
