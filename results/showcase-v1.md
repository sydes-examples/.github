# Showcase (v1)

Five PRs from the 15-case manual calibration suite, chosen to demonstrate
what Sydes actually does — affected-path tracing, test mapping,
verification gaps, and honest `PARTIAL` behavior — not chosen because they
all pass. See the [full validation summary](manual-v1-public-summary.md)
for the complete 15-case picture.

## Python — [PY-M-01](https://github.com/sydes-examples/Kokoro-FastAPI/pull/3)

- **What Sydes recovered:** traced a change to `check_pause_budget` (a
  shared validation function) forward to two independent routes,
  `POST /audio/speech` and `POST /dev/captioned_speech`, proving both, with
  a directly relevant new test mapped to each.
- **What remained unverified:** nothing material — this is the suite's
  cleanest result (support: PASS).
- **Why it's interesting:** clean affected-path tracing across two separate
  entrypoints sharing one changed function.

## Go — [GO-M-01](https://github.com/sydes-examples/simplebank/pull/2)

- **What Sydes recovered:** located the right nodes in the call graph
  (`CreateUserTx`, `CreateUser`, `TestCreateUserAPI`).
- **What remained unverified:** the impact itself — whether decoupling a
  task-queue failure from a DB transaction's commit changes observable
  behavior is a semantic fact a pure call-graph trace can't establish, so
  it stayed `inferred` (0.85–0.9 confidence), never promoted to `proven`
  (support: PARTIAL).
- **Why it's interesting:** the honest boundary between `proven` and
  `inferred` evidence — Sydes never silently upgrades one to the other.

## TypeScript — [TS-M-01](https://github.com/sydes-examples/domain-driven-hexagon/pull/2)

- **What Sydes recovered:** structurally resolved a NestJS `@nestjs/cqrs`
  `CommandBus` dispatch (a command class resolved to its handler via
  decorator metadata at runtime, not a plain function call).
- **What remained unverified:** at initial measurement, a new e2e test had
  never been observed passing; it has since been run to a real green
  result (revised 2026-09-09 — see the case's `verification_update`).
  Nothing remains unverified now (support: PASS).
- **Why it's interesting:** shows both a genuinely dynamic dispatch
  mechanism being resolved, and a verification gap being closed after the
  fact rather than silently assumed.

## Java — [JAVA-M-01](https://github.com/sydes-examples/spring-boot-demo/pull/2)

- **What Sydes recovered:** proved `DELETE /api/monitor/online/user/kickout`
  depends on the changed `MonitorService.kickout`, and correctly mapped a
  brand-new test (`MonitorServiceTest.kickoutFiltersBlankAndDuplicateNames`)
  added against a path that had zero prior test coverage.
- **What remained unverified:** nothing material — a clean result
  (support: PASS).
- **Why it's interesting:** a clean medium-complexity example, including
  test mapping onto a path with no pre-existing coverage.

## Rust (partial) — [RS-M-01](https://github.com/sydes-examples/Rocket/pull/2)

- **What Sydes recovered:** proved the real route (`DELETE /{id}`) — but
  also "proved" two unrelated routes (`DELETE /`, `DELETE /file`)
  belonging to entirely different example crates in the same Cargo
  workspace.
- **What remained unverified:** whether the extra routes were genuine —
  they weren't; confirmed false positives from route detection matching by
  bare function name rather than scoping by crate (support: PARTIAL).
- **Why it's interesting:** a correct proven path and a confirmed false
  positive in the same result — a genuine, calibrated symptom of Rust's
  experimental support, not a one-off bug.
