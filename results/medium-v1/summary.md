# Medium-case suite (v1) — results

> **Update (2026-09-09, release-prep):** TS-M-01's new e2e scenario, disclosed
> at initial measurement as "written, not observed passing," was subsequently
> run to a real green result
> ([run](https://github.com/sydes-examples/domain-driven-hexagon/actions/runs/34295704254),
> 8/8 tests passed) via a temporary, since-removed CI-only workflow. This
> closes the sole reason TS-M-01 was PARTIAL rather than PASS — **TS-M-01 is
> revised to PASS** below. See `ts-m-01.json`'s `verification_update` field
> for the exact command/workaround. No other case or metric in this file
> changed; the original canonical Sydes measurements are untouched.

Five medium-complexity calibration cases, one per language, implemented exactly
per the frozen preregistration
([`examples/medium-v1/`](../../examples/medium-v1/), commit `79a0c5f`), then run
once each against the same frozen Sydes SHA used for the simple-v1 baseline:
`256f4f9e5e09956d6014bf450f4462f616e826ce`. All five patches were frozen
(manifest committed at `285903a`) before any Sydes run. All five canonical runs
completed on the first attempt with the correct SHA installed — zero infra
reruns needed.

## Table 1 — Results

| Case | Lang | Verdict | Risk | Proven | Flows | Obligations | GT discovered | GT mapped | Support |
|---|---|---|---|---|---|---|---|---|---|
| PY-M-01 | Python | VERIFICATION INCOMPLETE | MEDIUM | 2 | 2 | 11 | yes | yes | **PASS** |
| GO-M-01 | Go | VERIFICATION INCOMPLETE | MEDIUM | 0 (3 inferred) | 1 | 1 | yes | yes | **PARTIAL** |
| TS-M-01 | TypeScript | VERIFICATION INCOMPLETE | HIGH | 1 (1 inferred) | 1 | 3 | yes | yes (revised 2026-09-09, see note above) | **PASS** |
| JAVA-M-01 | Java | VERIFICATION INCOMPLETE | MEDIUM | 1 | 1 | 2 | yes | yes | **PASS** |
| RS-M-01 | Rust | VERIFICATION INCOMPLETE | MEDIUM | 4 (2 false-positive) | 3 | 3 | yes | yes | **PARTIAL** |

All five share the same `verdict: VERIFICATION INCOMPLETE` — this is expected
and general, not case-specific: this Sydes CI check performs structural
verification only and does not execute any case's actual test suite itself
(`test_executions_count=0` and `ci_suite=disabled` in all five raw results).
A passing structural check with an incomplete verdict is the documented,
expected shape of this tool's output, not a failure signal.

## Table 2 — Expected path recovery

| Case | Expected path recovered? | False path? | Major gap |
|---|---|---|---|
| PY-M-01 | Yes — both routes proven | No | None; 3 unresolved symbols are the new test functions themselves (correctly not treated as production entrypoints) |
| GO-M-01 | Partially — correct nodes located in the flow graph (CreateUserTx, CreateUser, TestCreateUserAPI) | No | Impact only reached "inferred" (LLM), never "proven" — an honest limit on proving a transactional/async-failure semantic change structurally |
| TS-M-01 | **Yes, and notably** — DeleteUserService.execute appears in the *proven* flow's changed_nodes, meaning the `@nestjs/cqrs` CommandBus decorator dispatch was successfully bridged | No | None remaining — new e2e test confirmed passing 2026-09-09 (see update note above) |
| JAVA-M-01 | Yes — clean single proven flow, new test method directly mapped | No | None |
| RS-M-01 | Yes — DELETE /{id} (the real route) is among the proven flows | **Yes — two extra routes** ("DELETE /", "DELETE /file") from unrelated Cargo-workspace examples, confirmed by source inspection | Known Rust route-detection limitation (see Findings) |

## Per-case findings

**PY-M-01 (PASS).** Clean result. Both entrypoints (`POST /audio/speech`,
`POST /dev/captioned_speech`) proven with `check_pause_budget` as the changed
symbol, matching the preregistration exactly.

**GO-M-01 (PARTIAL).** The flow's own node graph correctly contains
`CreateUserTx`, `CreateUser`, and `TestCreateUserAPI` — the right call chain
was structurally located — but the overall impact was only accepted as
`inferred` (LLM-based, confidence 0.85–0.9), never `proven`. This is read as
an honest, appropriate limit: whether decoupling `AfterCreate`'s failure from
the transaction commit actually changes `POST /users`' observable behavior is
a transactional-semantics fact, not something a pure call-graph proof can
establish — and it was correctly *not* promoted to "proven" from LLM
inference, respecting proof-semantics integrity.

**TS-M-01 (PASS, revised 2026-09-09).** The proven flow's `changed_nodes`
includes `DeleteUserService.execute` — Sydes successfully traced through the
`@nestjs/cqrs` `CommandBus`'s decorator-based dynamic dispatch, the exact
structural challenge this case was chosen to probe. At initial measurement
this was marked PARTIAL solely because the new e2e scenario had never been
observed passing (local Docker/Postgres was unavailable in the sandbox). That
gap has since been closed: the scenario now has a real, observed green run
(8/8 tests passed) via a temporary CI-only workflow, using a pinned Postgres
15 service container in place of the repo's own docker-compose.yml (whose
floating `postgres:alpine` tag now resolves to Postgres 18+) and
`--legacy-peer-deps` (a pre-existing `slonik`/`@slonik/migrator` conflict in
the upstream repo). Neither workaround touched application or test code.

**JAVA-M-01 (PASS).** Clean single proven flow. Notably, the brand-new
`MonitorServiceTest.kickoutFiltersBlankAndDuplicateNames` — added against a
path that had *zero* existing test coverage before this PR (O5 per
preregistration) — was correctly discovered and mapped.

**RS-M-01 (PARTIAL).** The real route (`DELETE /{id}`) was correctly proven.
But the result also proved two false-positive routes: `DELETE /` (matches
same-named `delete` handlers in `examples/cookies/src/message.rs` and three
`examples/databases/src/*.rs` files) and `DELETE /file` (matches
`examples/responders/src/main.rs`'s `#[delete("/file")]` handler) — confirmed
by direct source inspection of the Rocket workspace. Root cause: the
deterministic route-composition heuristic
(`deterministic_frameworks=express_mount_graph`, the same generic heuristic
already known to be misapplied to Rust from RS-S-01) appears to match routes
to the changed symbol by bare function name across the entire Cargo
workspace rather than scoping by crate/file. This is the **same** known,
already-documented Rust limitation as RS-S-01 — there it caused
under-detection (`affected_flows=0`); here it causes over-detection
(false-positive routes). Recorded as a further symptom of the same accepted
limitation, not a new architectural gap. **Not fixed**, per instructions.

## Support classification rationale

- **PASS** (PY-M-01, JAVA-M-01, TS-M-01 as of 2026-09-09): expected path
  fully and cleanly proven, GT test correctly mapped and confirmed passing,
  no false positives.
- **PARTIAL** (GO-M-01, RS-M-01): each has a genuine, disclosed reason short
  of a clean pass — GO-M-01's impact only reached "inferred"; RS-M-01's
  correct route is contaminated by known-cause false positives. None reflect
  a hidden or minimized failure.
- No case reached **FAIL/unsupported** — none produced a wrong or absent
  expected path outright.

## Known limitations reflected in this suite

- **Rust remains PARTIAL** (RS-M-01) — the same `express_mount_graph`
  route-detection heuristic misapplied to Rust, now shown to cause
  over-detection as well as the previously-known under-detection.
- **No new Java CBM proxy-noise issue** was encountered in JAVA-M-01 (this
  case's path was deliberately chosen to avoid Spring Data JPA proxy
  involvement — see preregistration).
- **TS CQRS decorator dispatch was successfully resolved** in this instance —
  this is the opposite of a limitation, and is called out explicitly since
  the preregistration flagged it as an open question.
- **Go's async-task-queue boundary (worker dispatch) could not be
  structurally proven**, only inferred — an honest limit worth carrying into
  the hard-case Go candidate search.
