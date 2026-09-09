# Hard-case suite (v1) — results

> **Update (2026-09-09, release-prep):** TS-H-01's new e2e scenario was
> subsequently run to a real green result
> ([run](https://github.com/sydes-examples/domain-driven-hexagon/actions/runs/34295699305),
> 8/8 tests passed), using the same temporary, since-removed CI-only
> workaround as TS-M-01 (see `ts-h-01.json`'s `verification_update` field).
> This does **not** change TS-H-01's support_status: the reason it is
> FAIL/unsupported is structural (`affected_flows=0` — Sydes could not
> connect `Address.validate()` back to `POST /v1/users` at all), independent
> of whether the test itself passes. It is noted here only because the test
> was previously, incorrectly listed as "discovered: false" — corrected to
> "discovered: true, mapped: false" (Sydes never had a flow to map it to).

Five hard-complexity calibration cases, one per language, implemented
exactly per the frozen preregistration
([`examples/hard-v1/`](../../examples/hard-v1/), commit `15bbfbb`), then run
once each against the SAME frozen Sydes SHA used for simple-v1 and
medium-v1: `256f4f9e5e09956d6014bf450f4462f616e826ce` (no generic Sydes fix
occurred during this study, so no SHA change was warranted). All five
patches were frozen (manifest committed at `e8828f5`) before any Sydes run.
All five canonical runs completed on the first attempt with the correct SHA
installed — zero infra reruns needed.

## Table 1 — Results

| Case | Lang | Verdict | Risk | Proven | Flows | Obligations | GT discovered | GT mapped | Support |
|---|---|---|---|---|---|---|---|---|---|
| PY-H-01 | Python | VERIFICATION INCOMPLETE | HIGH | 2 (+2 inferred) | 2 | 11 | yes | yes | **PASS** |
| GO-H-01 | Go | VERIFICATION INCOMPLETE | MEDIUM | 0 (1 inferred) | 0 | 0 | unclear | no | **FAIL / unsupported** |
| TS-H-01 | TypeScript | VERIFICATION INCOMPLETE | MEDIUM | 0 (3 inferred) | 0 | 0 | yes (discovered 2026-09-09, see update note above) | no | **FAIL / unsupported** |
| JAVA-H-01 | Java | VERIFICATION INCOMPLETE | MEDIUM | 2 | 1 | 1 | yes | yes | **PARTIAL** |
| RS-H-01 | Rust | VERIFICATION INCOMPLETE | MEDIUM | 3 (self-referential) | 0 | 0 | no (0 test files found repo-wide) | no | **FAIL / unsupported** |

This hard suite has a materially different shape than simple-v1 (5/5 PASS
or PARTIAL) and medium-v1 (2 PASS, 3 PARTIAL): **three of five cases hit a
genuine, confirmed structural wall** (0 affected_flows, 0 obligations).
This is the expected, intended outcome of choosing genuinely hard cases —
per instructions, these are recorded as findings, not fixed.

## Table 2 — Expected path recovery

| Case | Expected path recovered? | False path? | Major gap |
|---|---|---|---|
| PY-H-01 | Yes — both routes proven | No | None |
| GO-H-01 | **No — 0 affected_flows** | No | Confirmed: Sydes has no entrypoint concept for a non-HTTP asynq task-consumer, even though it detects the repo's normal gRPC routes fine (known_entrypoints=7, deterministic_routes_found=7) |
| TS-H-01 | **No — 0 affected_flows** | No (LLM guesses are plausible, not wrong) | Confirmed: reverse/backward reachability from a deeply-nested value object, through an aggregate, through CQRS dispatch, back to the controller is not achieved structurally |
| JAVA-H-01 | Partially — one real route (`POST /api/auth/logout`) proven | No | The true cross-cutting breadth (every authenticated route via the shared filter) was not captured — only one concretely-reachable route was found |
| RS-H-01 | **No — 0 affected_flows, 0 deterministic routes** | Self-referential "proven" impacts are test names, not real routes — not a false positive, but not a real result either | Confirmed: Sydes has zero route-detection support for Axum's `.route()`-registration style — a stronger, distinct gap from Rocket's known misapplied-heuristic issue |

## Per-case findings

**PY-H-01 (PASS).** The deepest Python chain in this study (SSML router →
SSML service → shared schema constant → text_processor → tts_service,
spanning two HTTP routes) traced and proven cleanly. Two additional
"inferred" entries are LLM-generated descriptive restatements of the same
proven fact, not evidence of a gap.

**GO-H-01 (FAIL / unsupported).** This is a clean, confirmed architectural
finding, exactly as the preregistration anticipated: Sydes' entrypoint
model has **no representation at all for a non-HTTP, task-queue consumer**
(an asynq task-type dispatched via a `ServeMux`). All 6 changed symbols
went unresolved; the only accepted impact is an uncorroborated LLM guess.
This is a direct, deeper extension of GO-M-01's finding (which showed the
producer side could only reach "inferred," never "proven," at the same
async boundary) — the consumer side, having no HTTP path to start from at
all, gets nothing.

**TS-H-01 (FAIL / unsupported).** Sydes could not structurally connect a
validation rule buried inside a value object (`Address.validate()`) back
up through entity construction and CQRS dispatch to `POST /v1/users` — the
reverse direction of TS-M-01's successful controller-to-handler trace, and
a genuinely harder direction. All three accepted impacts are LLM inferences
of varying confidence (0.6–0.9) and corroboration. One inference
interestingly surfaced a previously-unknown-to-us `CreateUserCliController`
— a parallel CLI interface into user creation — a real, if unproven,
discovery worth independent follow-up (out of scope for this study).

**JAVA-H-01 (PARTIAL).** A genuinely positive, if narrow, result: Sydes
found and proved that `POST /api/auth/logout`'s handler really does depend
on the changed `JwtUtil.parseJWT`, and correctly mapped the new
`JwtUtilTest` to it. But the preregistered ground truth was that this
change affects **every** authenticated route via a shared servlet filter —
Sydes' route model has no way to represent that class-wide breadth, so it
surfaced one concrete, correctly-reachable route rather than the true
scope. A real result, honestly narrower than the full preregistered claim.

**RS-H-01 (FAIL / unsupported).** The starkest Rust finding in the whole
study: `deterministic_routes_found=0, deterministic_frameworks=none` — not
even the (incorrect) `express_mount_graph` heuristic that fired for Rocket
in RS-M-01 activated here. Sydes has no detector at all for Axum's
`.route(path, get(handler))` registration style. The three "proven"
accepted impacts are self-referential matches of the new test functions to
themselves (`kind: decorated`), not real route-level proof — reported
honestly as such rather than counted toward a pass. This reinforces, with a
second and different Rust web framework, that Rust route/entrypoint
detection is a genuine, general gap in this Sydes version — not confined to
Rocket's specific quirks.

## Support classification rationale

- **PASS** (PY-H-01): clean, full structural proof of the preregistered path.
- **PARTIAL** (JAVA-H-01): a real, correct, narrower-than-preregistered
  structural result — not nothing, not everything.
- **FAIL / unsupported** (GO-H-01, TS-H-01, RS-H-01): `affected_flows=0` and
  `obligations=0` in every case — a genuine, confirmed structural wall, each
  for a different, specific, well-understood reason (no non-HTTP entrypoint
  model; no deep backward value-object reachability; no Axum route
  detection). None of these were tuned around, patched, or hidden.

## Known limitations reflected in this suite

- **Rust remains PARTIAL/weak**, now confirmed across TWO different web
  frameworks (Rocket's misapplied heuristic in RS-M-01; Axum's complete
  absence of detection in RS-H-01) — this is a genuine, general Rust
  route-detection gap, not a single-framework quirk.
- **No entrypoint model exists for non-HTTP consumers** (message/task
  queues) in Go, and by extension likely in any language — GO-H-01 is the
  first case in this study to test this directly, and it failed cleanly.
- **Deep backward/upward reachability (value object -> aggregate -> CQRS
  handler -> controller) is not yet achieved** in TypeScript, in contrast
  to the successful forward trace already shown by TS-M-01.
- **Route-level modeling cannot represent cross-cutting, filter-level
  concerns** that affect a whole class of endpoints (JAVA-H-01) — Sydes
  can prove ONE concretely-reachable route depends on a changed symbol, but
  has no mechanism to claim or verify the broader class-wide breadth.
- None of these were fixed, per explicit instruction — each is recorded as
  a canonical finding / backlog item for future architectural work.
