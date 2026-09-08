# Medium-case suite (v1) — preregistration

Five medium-complexity calibration cases, one per language, selected and
preregistered **before** any implementation or Sydes run. See
[`../../results/simple-v1/`](../../results/simple-v1/) for the completed
simple-band baseline this suite follows.

Selection followed the study's structural-complexity framework:
propagation depth (D0–D4), breadth (B1–B4), observability (O1–O5), and
archetype (A1–A8). Per case, all four are recorded in the case's own YAML
file, along with the manually-established ground truth (changed symbols,
entrypoints, tests) — established from source inspection alone, never from
running Sydes. **No numeric complexity-score formula was found documented
in either this repo or the Sydes repo** at selection time; the registry's
existing convention (see `../README.md`) records categorical D/B/O labels
directly rather than a derived number, so that is what these files do too.
Each case's qualitative complexity tier ("medium") is a judgment call
against the band description given for this suite (D2/D3, B2/B3,
multi-component, existing-or-addable test, not single-hop/local), not a
computed score — flag this if a canonical numeric formula exists elsewhere
and these should be recomputed against it.

## The five cases

| ID | Language | Repo | Path depth | Primary archetype | D | B | O |
|---|---|---|---|---|---|---|---|
| [PY-M-01](py-m-01.yaml) | Python | Kokoro-FastAPI | 2 routers → text_processor.py | error-behavior | D2 | B3 | O1 |
| [GO-M-01](go-m-01.yaml) | Go | simplebank | gapi → db/sqlc tx → worker | dependency-interaction | D3 | B3 | O1 |
| [TS-M-01](ts-m-01.yaml) | TypeScript | domain-driven-hexagon | controller → CommandBus → handler → domain/repo | control-flow | D3 | B3 | O4 |
| [JAVA-M-01](java-m-01.yaml) | Java | spring-boot-demo | controller → service → RedisUtil | data-semantics | D2 | B2 | O5 |
| [RS-M-01](rs-m-01.yaml) | Rust | Rocket | route → Task fn → Context fn → Task fn | error-behavior | D2 | B2 | O1 |

## Diversity check

Primary archetypes: error-behavior (PY), dependency-interaction (GO),
control-flow (TS), data-semantics (JAVA), error-behavior (RS) — four
distinct primary archetypes, with PY and RS sharing "error-behavior" as
their primary label. This is disclosed rather than smoothed over: the two
are mechanistically different (PY: reject-vs-silently-clamp against a
numeric threshold in a text-validation pipeline; RS: detect a
zero-rows-affected DB result and route it into an existing
error-rendering path), but both are still fundamentally about a rejected/
error condition rather than, e.g., a data-transformation or config
archetype. D/B labels span D2–D3 and B2–B3 across the suite (not all
identical); O labels span O1/O4/O5, which is a deliberate, honestly-
reported spread — JAVA-M-01 and TS-M-01 in particular have real
observability gaps (O5: no existing test at all; O4: existing test is
happy-path-only) rather than being selected only where coverage was
already comfortable.

## Test feasibility (Phase E — confirmed empirically, no code changed)

- **PY-M-01**: `api/tests/test_pause_bounds.py` — 7 tests, 0.68s, no live
  services, no ML/GPU. Confirmed via `.venv/bin/python -m pytest`.
- **GO-M-01**: `go test ./gapi/... -run TestCreateUserAPI` — 4 subtests,
  0.28s, fully mock-based (mockdb + mockwk), no live DB. Confirmed.
- **TS-M-01**: no unit-test option exists in this repo at all (zero
  `*.spec.ts` files repo-wide); the only test type is e2e via
  jest-cucumber, which requires a live Postgres test database
  (`tests/setup/jestGlobalSetup.ts` enforces a "test"-named DB;
  `docker/docker-compose.yml` provisions it). Not run in this session —
  recorded as a real infrastructure cost, not attempted/faked.
- **JAVA-M-01**: no existing test for this path. A local
  `mvn -pl demo-rbac-security -am test` attempt failed on Lombok
  "cannot find symbol" errors, traced to this machine's default JDK (21)
  vs. the repo's pinned `java.version=1.8` (Lombok's known incompatibility
  with newer JDKs' encapsulated compiler internals) — confirmed via the
  repo's own `.github/workflows/maven.yml`, which correctly pins
  `java-version: 1.8` for CI. Not a defect in the candidate; local
  compilation simply could not be confirmed in this session.
- **RS-M-01**: `cargo test` in `examples/todo` — full network build
  (18.27s first compile) then 5/5 existing tests passed in 1.74s. Uses a
  local SQLite file via Diesel (no network service). Confirmed working
  end-to-end.

## Explicitly out of scope for this suite

No code was written or modified for any of the five proposed changes
above — every file in this directory is inspection + preregistration
only. No Sydes run has been performed against any of these cases.
