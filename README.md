# sydes-examples/.github

Central integration point for public Sydes demo repositories under the
[sydes-examples](https://github.com/sydes-examples) organization.

This repository hosts, in one place, the pieces every example repo would
otherwise have to copy:

- [`.github/workflows/sydes-verify.yml`](.github/workflows/sydes-verify.yml) —
  the reusable GitHub Actions workflow that runs `sydes verify-change` on a
  PR, renders the result, upserts a persistent PR comment, writes the job
  summary, and uploads the artifact.
- [`scripts/render_sydes_pr.py`](scripts/render_sydes_pr.py) — the
  deterministic, generic renderer that turns a `sydes-result.json` into the
  Markdown used for both the PR comment and the job summary.
- [`CONTRACT.md`](CONTRACT.md) — the frozen v1 artifact/presentation
  contract this workflow and renderer implement.
- [`examples/`](examples/) — a lightweight, machine-readable registry of
  validation cases across all example repositories (see
  [`examples/README.md`](examples/README.md)).

## Using this from an example repository

```yaml
name: Sydes

on:
  pull_request:
    branches: [ "master" ]   # or your default branch

permissions:
  contents: read
  pull-requests: write

jobs:
  sydes:
    uses: sydes-examples/.github/.github/workflows/sydes-verify.yml@main
    with:
      repo_alias: app
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

That's the entire integration a new example repository needs. See
[Kokoro-FastAPI's caller workflow](https://github.com/sydes-examples/Kokoro-FastAPI/blob/master/.github/workflows/sydes.yml)
for a real, working reference.

## Why centralize here

Before this repository existed, every example repo carried its own full copy
of the workflow steps and the renderer script. That meant a bug fix or
presentation change had to be repeated, by hand, in every repository — which
does not scale past one demo. Centralizing here means:

- one place to fix or improve the renderer,
- one place to version the presentation contract (`CONTRACT.md`),
- and a new example repo needs only a ~15-line caller workflow plus a
  metadata record, not a copy of the implementation.

## Versioning

For now, example repos call this workflow at `@main`. That is intentionally
simple for v1 — every consumer currently tracks the latest version. Pinning
consumers to a tag or SHA once this needs to stabilize independently of
in-flight changes is a natural next step, not done yet.
