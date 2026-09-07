# Example case registry

One YAML file per validation case, named `<repo-slug>-<case-id>.yaml`
(lowercase, hyphenated), e.g. `kokoro-fastapi-py-s-01.yaml`.

## Why a central registry, not per-repo files

The eventual validation report needs to enumerate every case across every
example repository. A central registry is one directory to glob, independent
of how many repos exist or whether a given fork is later reset or deleted.
The tradeoff is that adding a case means two commits (one in the example
repo for the actual change, one here for the record) instead of one — an
acceptable cost for a handful of cases in v1.

## Fields

Only the fields below exist today. Do not add more without a concrete need —
this is a v1 convention meant to support reproducing the eventual report, not
a general-purpose case-tracking schema.

```yaml
id: PY-S-01                          # stable case identifier
language: python
source: manual                       # how the case was produced, e.g. manual, generated
repo: sydes-examples/Kokoro-FastAPI  # owner/repo
pr: 1                                # PR number in that repo
complexity: simple                   # structural class
propagation: D1                      # propagation-depth target
breadth: B1-B2                       # impact-breadth target
observability: O1                    # observability target
ground_truth_tests:                  # manually established, not Sydes-reported
  - test_get_model_name_strips_whitespace
```

`ground_truth_tests` is the human-established expected answer for what
verifies the change — used to evaluate whether Sydes independently
identified it, never told to Sydes as input.

Optional fields, added only when a case needs them:

- `route`, `handler`, `changed_symbol` — the preregistered live production
  call path (`route → handler → changed_symbol`), when the case is a
  live/positive support-gate case.
- `status` — set only when a case's role differs from the default (a live
  positive case). `dead_code_negative` marks a case whose target symbol has
  no live production caller, kept intentionally as a negative check that
  Sydes does not invent a path for genuinely unreachable code. `note` gives
  the one-paragraph reason alongside it.
