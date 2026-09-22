# Releasing agent86

Cutting a release is pushing a tag. Everything after that — pre-flight, build, verification,
publish, and the GitHub Release — is `.github/workflows/release.yml`, which exists so that no
part of a release depends on what happens to be installed on the machine that cut it.

This document is the procedure and the one-time setup behind it. The rules it enforces live in
`scripts/check_release.py`; if the two ever disagree, the script wins.

---

## The procedure

### 1. Bump both version lines

The version is a literal in **two** files and they must agree:

```toml
# pyproject.toml
[project]
version = "1.1.0"
```

```python
# src/agent86/__init__.py
__version__ = "1.1.0"
```

`agent86.__version__` is deliberately *not* derived from `importlib.metadata.version("agent86")`.
Both approaches keep `agent86 --version` correct in an editable install and in a wheel, so the
tie-breakers are cost and failure mode: `importlib.metadata` is a real import on the cold-start
path (an explicit constraint of this project), and `version()` raises `PackageNotFoundError` when
the package is merely on `sys.path` and not installed — a source checkout, a vendored copy, a
zipapp — which turns `--version` into a crash exactly where it is least expected. The cost of a
literal is that it can drift, and that drift is a *release* concern, not a runtime one: the
pre-flight below catches it, and the packaging tests assert the same equality against the built
wheel.

### 2. Write the CHANGELOG section

Add `## [X.Y.Z] - YYYY-MM-DD` to `CHANGELOG.md` above the previous release, in the house style:
a short lead paragraph saying what the milestone was *for*, then Added / Changed / Fixed /
Security. Add the link reference at the bottom of the file:

```markdown
[1.1.0]: https://github.com/tdfleming/agent86CLI/releases/tag/v1.1.0
```

Two rules, both mechanically enforced:

- the section must have a **body** — this text *is* the GitHub Release notes, extracted by
  `scripts/changelog_section.py`, which shares its parser with the pre-flight so the check and the
  extraction cannot disagree;
- **`## [Unreleased]` must be empty.** Anything still sitting there was meant for this release;
  move it into the version's section or cut a different version.

### 3. Run the pre-flight locally

```bash
python scripts/check_release.py --tag v1.1.0
```

It prints one line per check and exits 0 only when all of them pass:

1. `pyproject.toml`'s version is well-formed, and the git tag, `project.version` and
   `agent86.__version__` all name the same version;
2. `CHANGELOG.md` has a `## [<version>]` section, and it has a body;
3. `## [Unreleased]` is empty;
4. `README.md`, `LICENSE` and `docs/ARCHITECTURE.md` are present.

Every check runs even after one fails, so a single run shows every problem. Without `--tag` the
tag comparison is skipped — which is how CI's `package` job runs it on every branch build, to
catch version/CHANGELOG drift long before anyone tags.

Also worth running before tagging, since they are what the workflow will run against the artifact:

```bash
pytest -m packaging tests/packaging    # see "Running the packaging tests locally" below
ruff check . && mypy src/agent86 && pytest
```

### 4. Tag and push

Tag the commit that contains the bump and the CHANGELOG section — nothing else is read from the
repository at publish time.

```bash
git tag v1.1.0
git push origin v1.1.0
```

Do **not** move or re-point a tag that has already been pushed: PyPI refuses to reuse a filename,
so a re-run of the same version fails at the publish step whatever the tag points at. If a release
goes out wrong, cut the next patch version.

---

## What the workflow does

`.github/workflows/release.yml` runs on `push` of a `v*` tag (and on `workflow_dispatch`, see
below). It has four jobs:

**`build` — pre-flight, build and verify** (ubuntu-latest)

1. `python scripts/check_release.py` — first, and fail-fast. The tag comes from `GITHUB_REF_NAME`
   on a tag build, so nothing has to be passed in.
2. `uv build` — sdist and wheel.
3. `twine check dist/*` — metadata and README render gate.
4. `pytest -m packaging tests/packaging` — the packaging tests build their own artifacts into a
   temp dir and install the wheel into a throwaway venv, so they verify the thing that is about to
   be published rather than the repository.
5. `scripts/changelog_section.py <version> --output release-notes.md`.
6. Uploads `dist/` and `release-notes.md` as artifacts.

**`publish-pypi`** — downloads `dist/` and publishes with `pypa/gh-action-pypi-publish` through
the **`pypi`** GitHub environment, using `id-token: write` (OIDC). No API token exists in this
repository.

**`publish-testpypi`** — the same, against `https://test.pypi.org/legacy/` with `skip-existing`,
through the **`testpypi`** environment. Only runs on `workflow_dispatch` with `target: testpypi`.

**`github-release`** — needs both `build` and `publish-pypi`, and only runs on a real tag push.
Creates the GitHub Release with `gh release create`, titled `agent86 <version>`, with
`release-notes.md` as the body and the built distributions attached.

Concurrency is grouped per ref and **not** cancel-in-progress: a publish that has started must not
be interrupted half-way.

---

## One-time setup

This has to be done once per index, by someone who can administer both the PyPI project and the
GitHub repository. Trusted publishing is configured on the *index* side; the GitHub side only
needs the environments to exist.

### PyPI

1. Sign in to <https://pypi.org> and open **Your projects → agent86 → Manage → Publishing**. If
   the project does not exist yet, use **Your account → Publishing → Add a pending publisher**
   instead — a pending publisher creates the project on the first successful upload.
2. Add a **GitHub** publisher with exactly:

   | Field | Value |
   |---|---|
   | Owner | `tdfleming` |
   | Repository | `agent86CLI` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. In the GitHub repository, **Settings → Environments → New environment** named **`pypi`**.
   Add required reviewers if a publish should need a human approval; nothing else is needed — no
   secrets, no tokens.

### TestPyPI

The same, at <https://test.pypi.org>, with the environment name **`testpypi`**, and a matching
GitHub environment called `testpypi`. TestPyPI is a separate account and a separate project
registration; the two do not share credentials or state.

### Why this shape

The environment name is part of what PyPI verifies in the OIDC claim, so a workflow that is not
running in the `pypi` environment cannot publish, even from this repository. That is also why the
publish steps are separate jobs: the environment (and the `id-token: write` permission) is scoped
to the two jobs that need it, and the build job — which runs test code — has neither.

---

## Rehearsing on TestPyPI

A version number can only be published once; a filename on PyPI can never be reused. So rehearse
the publish path on TestPyPI, where a burned version number costs nothing:

1. GitHub → **Actions → Release → Run workflow**.
2. Pick the branch, leave **Index to publish to** at its default `testpypi`, and run it.

The whole pipeline runs — pre-flight, build, `twine check`, packaging tests — and publishes to
TestPyPI with `skip-existing: true`, so a re-run of the same version is a no-op rather than a
failure. No GitHub Release is created: that job is gated on a real tag push.

Note that `workflow_dispatch` runs against a **branch**, so the pre-flight's tag comparison is
skipped; the version/CHANGELOG checks still run. Install the result with:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ agent86
```

The extra index is required — agent86's dependencies live on real PyPI, not on TestPyPI.

Choosing `pypi` as the dispatch target publishes to the real index from a branch. That exists for
recovering a release whose tag build failed *after* the tag was pushed; it is not the normal path.

---

## Running the packaging tests locally

The packaging tests run `python -m build` for real and install the resulting wheel into a
throwaway virtualenv, so they assert the artifact a user would get rather than the source tree:
the wheel's contents and metadata, the version equality between `pyproject.toml` and
`agent86.__version__`, the `agent86` console entry point running from that venv, and the
lazy-import contract holding in an installed copy.

That costs roughly 25 seconds on a warm pip cache, which is far too slow for the default run, so
everything in `tests/packaging/` carries a `packaging` marker and `pyproject.toml` sets
`addopts = "-m 'not packaging'"`. A `-m` on the command line is appended after `addopts` and
therefore wins, which is how both CI and you opt in:

```bash
pip install -e ".[dev]"          # build + twine come with the dev extra
pytest -m packaging tests/packaging -q
```

To run *everything*, including them:

```bash
pytest -m "packaging or not packaging"
```

CI runs the same selection in a dedicated `package` job on Ubuntu **and** Windows, because the
wheel's console entry point and the sdist's file list are the two things most likely to differ
between platforms.

---

## After a successful first publish

**Done for 1.0** (`06ca3a4`, 2026-09-21): `pyproject.toml` now declares
`Development Status :: 5 - Production/Stable`, flipped from `4 - Beta` once 1.0.0 was live on
PyPI. The published 1.0.0 artifact itself still carries `4 - Beta` — a published classifier
cannot be changed retroactively — so the new one first reaches PyPI with the next release.

The rule this followed, for the next major: the classifier is a claim about a *published*
artifact, and nothing is published at the moment a tag is cut, so it flips in the first release
**after** the version it describes is live — never in the same commit as the tag.
