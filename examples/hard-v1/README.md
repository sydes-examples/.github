# Hard-case suite (v1) — preregistration

Five hard-complexity calibration cases, one per language, selected and
preregistered **before** any implementation or Sydes run, following the
completed [medium-v1](../medium-v1/) suite. Target complexity: >=15 under
the study's D(epth 0-4)/B(readth 1-4)/O(bservability 1-5) framework.

## The five cases

| ID | Language | Repo | Path | Archetype | D | B | O |
|---|---|---|---|---|---|---|---|
| [PY-H-01](py-h-01.yaml) | Python | Kokoro-FastAPI | SSML rate-composition (ssml.py -> text_processor.py -> tts_service.py, 2 routes) | cross-component | D3-D4 | B4 | O3 |
| [GO-H-01](go-h-01.yaml) | Go | simplebank | asynq task consumer ProcessTaskSendVerifyEmail (non-HTTP entrypoint) | dependency-interaction | D3-D4 | B3 | O5 |
| [TS-H-01](ts-h-01.yaml) | TypeScript | domain-driven-hexagon | CreateUser: CQRS -> Address value object -> transactional repo (+wallet event cascade) | cross-component | D4 | B4 | O4 |
| [JAVA-H-01](java-h-01.yaml) | Java | spring-boot-demo | JWT auth filter -> JwtUtil (Redis) -> RBAC service (cross-cutting, all authenticated routes) | cross-component | D4 | B4 | O5 |
| [RS-H-01](rs-h-01.yaml) | Rust | **realworld-axum-sqlx (NEW repo)** | AuthUser JWT extractor (cross-cutting, 5+ handler files) | cross-component | D3-D4 | B4 | O5 |

## A note on the Rust repo change

Rocket (used for RS-S-01 and RS-M-01) does not contain a genuine
hard-complexity candidate: an exhaustive scan of every `examples/*`
directory confirmed `examples/todo` (RS-M-01's location) is the *only*
location in the repo with a >=2-hop hand-written call chain, and it tops
out at D2/B2 — there is no third or fourth reachable hand-written
component. No other Rust repository existed locally. Per this study's own
explicit instruction ("if not, choose another Rust backend repo... do not
artificially manufacture complexity"), a new repo was sourced:
[launchbadge/realworld-axum-sqlx](https://github.com/launchbadge/realworld-axum-sqlx)
— an actively maintained (1,105 stars), real reference implementation of
the RealWorld/Conduit API spec, forked to
`sydes-examples/realworld-axum-sqlx` and onboarded with the same `sydes.yml`
workflow convention used by every other repo in this study. This does not
change Rust's overall PARTIAL support status — RS-H-01 tests the same
underlying Sydes Rust-support surface (deterministic route detection, the
`express_mount_graph` heuristic already shown to misfire on Rust in
RS-M-01) against a codebase with genuine depth, rather than switching
tools or lowering the bar.

## Diversity and continuity with medium-v1

Three of five hard cases deliberately extend a specific finding from
medium-v1 rather than picking an unrelated deeper path:

- **GO-H-01** targets the exact async boundary GO-M-01 showed Sydes can
  only reach via LLM inference (never proof) — from the *consumer* side
  this time, via a non-HTTP (task-queue) entrypoint.
- **TS-H-01** goes deeper than TS-M-01's already-successful CQRS trace,
  into a value object and a transactional repository base class, and
  documents (without exercising) an even deeper cross-module domain-event
  cascade.
- **RS-H-01**, forced onto a new repo, targets the same class of
  cross-cutting authentication logic as **JAVA-H-01** — both are
  "no-single-entrypoint" cases (a shared extractor / a security filter
  affecting every authenticated route), a genuinely different shape of
  impact than every case before it in this study, and a deliberate test of
  whether Sydes' route/entrypoint model can represent that at all.

Two cases (PY-H-01, JAVA-H-01) explicitly avoid ML-inference or Spring
Data JPA proxy dependencies respectively, consistent with the same
exclusions already applied at the medium tier.

## Test feasibility notes (methodology, not yet executed)

- **PY-H-01**: fully deterministic (no ML/GPU), 7 existing tests across 3
  files directly relevant; feasibility not yet re-verified locally (will
  be confirmed during implementation, following the same pattern as
  medium-v1).
- **GO-H-01**: existing `db.MockStore` reusable; a new mailer mock must be
  authored (no existing scaffold) — a real but small implementation cost.
- **TS-H-01**: same live-Postgres e2e-only situation as TS-M-01 — a new
  BDD scenario is the only test option; disclosed as a caveat, not hidden.
- **JAVA-H-01**: no existing test at this layer; the pure-Mockito pattern
  already proven by JAVA-M-01's `MonitorServiceTest` is directly reusable.
- **RS-H-01**: zero tests exist anywhere in the new repo, but the specific
  targeted function is DB-free and trivially unit-testable via a lazily
  connected `PgPool` (never queried) — confirmed via direct source reading
  during candidate search.

## Explicitly out of scope for this preregistration

No code has been written or modified for any of the five proposed changes
above. No Sydes run has been performed against any of these cases. This
file and the five case YAMLs are inspection + preregistration only.
