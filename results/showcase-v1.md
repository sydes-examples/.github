# Showcase (v1)

Five PRs from the 15-case manual calibration suite, chosen to demonstrate
what Sydes actually does — affected-path tracing, test mapping,
verification gaps, and honest `PARTIAL` behavior — not chosen because they
all pass. See the [full validation summary](manual-v1-public-summary.md)
for the complete 15-case picture.

## Python — [PY-M-01](https://github.com/sydes-examples/Kokoro-FastAPI/pull/3)

**What it demonstrates:** clean affected-path tracing across two separate
HTTP routes sharing one changed function, plus test mapping against an
existing test suite.

Sydes traced a change to `check_pause_budget` (a shared validation
function) forward to both `POST /audio/speech` and
`POST /dev/captioned_speech` — two independent routes that both depend on
it — and correctly proved both, with a directly relevant new test mapped
to each.

**Support outcome:** PASS. **Caveat:** none — this is the suite's cleanest result.

## Go — [GO-M-01](https://github.com/sydes-examples/simplebank/pull/2)

**What it demonstrates:** the honest boundary between `proven` and
`inferred` evidence. Sydes correctly located the right nodes in the call
graph (`CreateUserTx`, `CreateUser`, `TestCreateUserAPI`) but could only
accept the impact as `inferred` (LLM-reasoned, 0.85–0.9 confidence) — it
never promoted an unproven transactional-semantics claim to `proven`.

**Support outcome:** PARTIAL. **Caveat:** whether decoupling a task-queue
failure from a DB transaction's commit actually changes observable
behavior is a semantic fact a pure call-graph trace can't establish on its
own — recorded honestly as `inferred`, not silently upgraded.

## TypeScript — [TS-M-01](https://github.com/sydes-examples/domain-driven-hexagon/pull/2)

**What it demonstrates:** structural resolution of a genuinely dynamic
dispatch mechanism (a NestJS `@nestjs/cqrs` `CommandBus`, which resolves a
command class to its handler via decorator metadata at runtime, not a
plain function call) — plus a real example of a verification gap being
closed after the fact.

**Support outcome:** PASS (revised 2026-09-09 — the sole reason this case
was not already PASS was an e2e test that had never been observed
passing; it has since been run to a real green result). **Caveat:** none
remaining; see the case's `verification_update` for the resolved gap.

## Java — [JAVA-H-01](https://github.com/sydes-examples/spring-boot-demo/pull/3)

**What it demonstrates:** an honest, narrower-than-expected `PARTIAL`
result. Sydes proved that `POST /api/auth/logout` genuinely depends on the
changed `JwtUtil.parseJWT` — a real, correct discovery — but the
preregistered ground truth was that this change affects *every*
authenticated route via a shared servlet filter. Sydes' route model has no
way to represent that class-wide breadth, so it surfaced one concretely
reachable route instead of the full scope.

**Support outcome:** PARTIAL. **Caveat:** a real result, honestly narrower
than the true blast radius — not a false positive, but not the complete
picture either.

## Rust (partial) — [RS-M-01](https://github.com/sydes-examples/Rocket/pull/2)

**What it demonstrates:** both a correct proven path and a confirmed false
positive in the same result — Sydes proved the real route (`DELETE
/{id}`) but also "proved" two unrelated routes (`DELETE /`, `DELETE
/file`) belonging to entirely different example crates in the same Cargo
workspace, due to route detection matching by bare function name rather
than scoping by crate.

**Support outcome:** PARTIAL. **Caveat:** the correct route was recovered,
but the result is contaminated by known-cause false positives — a genuine
symptom of Rust's experimental route-detection support, not a one-off bug.
