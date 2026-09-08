# Canonical simple-case rerun — v1

One clean, reproducible baseline across all five simple calibration cases, run against a single frozen Sydes SHA.

- **Sydes SHA:** `256f4f9e5e09956d6014bf450f4462f616e826ce` (merged main after symbol-identity precision hardening, CBM canonical qualified identity support, the deterministic TS constructor-member bridge, and synthetic-edge canonical identity fixes)
- **Run date:** 2026-09-08
- Each case pinned via the existing `sydes_ref` mechanism to the exact SHA above; exactly one canonical run collected per case (no reruns needed — no infra failures, no wrong-SHA installs).

## Canonical results table

| Case | Lang | Verdict | Risk | Proven impacts | Affected flows | Obligations | GT test discovered | GT test mapped | Review | Support |
|---|---|---|---|---:|---:|---:|---|---|---|---|
| PY-S-02 | Python | VERIFICATION INCOMPLETE | HIGH | 3 | 3 | 30 | yes | yes | completed, 0 findings | PASS |
| GO-S-01 | Go | VERIFICATION INCOMPLETE | HIGH | 1 | 1 | 7 | yes | yes | completed, 0 findings | PASS |
| TS-S-02 | TypeScript | VERIFICATION INCOMPLETE | HIGH | 2 | 1 | 9 | yes | yes | completed, 0 findings | PASS |
| JAVA-S-01 | Java | VERIFICATION INCOMPLETE | MEDIUM | 9 (2 genuine) | 1 | 8 | yes | yes | completed, 0 findings | PASS |
| RS-S-01 | Rust | VERIFICATION INCOMPLETE | MEDIUM | 1 (+2 inferred) | 0 | 0 | yes | no | completed, 0 findings | PARTIAL |

Notes on the table (not normalized away — see per-case notes below for full detail):
- JAVA-S-01's "9 proven impacts" includes 7 known, separate CBM call-graph misattributions (Spring Data / inherited `save()` noise) alongside the 2 genuine ones (`save`, `POST /user`).
- RS-S-01 has 0 affected_flows / 0 obligations because no `EndpointCandidate` is discoverable for its route (no deterministic Rust route recognizer exists) — the structural proof stops at the `accepted_impacts` level (`POST /` proven), which is fully established. Two of RS-S-01's three accepted impacts (`DELETE /{id}`, `GET /{id}`) remain `inferred`, not proven.

## Structural metrics table

| Case | known_entrypoints | http_entrypoints | changed_symbols | unresolved | supporting_tests (distinct names) | mapped_tests |
|---|---:|---:|---:|---:|---:|---:|
| PY-S-02 | 174 | 3 | 2 | 0 | 10 | 10 |
| GO-S-01 | 7 | 1 | 3 | 2 | 1 | 1 |
| TS-S-02 | 18 | 0 | 2 | 1 | 1 | 1 |
| JAVA-S-01 | 520 | 1 | 3 | 0 | 1 (class-level) | 1 |
| RS-S-01 | 913 | 0 | 2 | 0 | 0 | 0 |

Note: TS-S-02 and RS-S-01 both report `http_entrypoints=0` in the raw `impact_interpreter` diagnostic even though each case genuinely has HTTP routes — both languages' routes are discovered entirely through the generic `route_index`/route-derived-entrypoint bridge rather than CBM's own native `http_entrypoints` classification. Reported as-is, not normalized.

## Ground-truth test evidence

| Case | GT test | Discovered | Mapped/selected | Supporting |
|---|---|---|---|---|
| PY-S-02 | `test_combine_voices_rejects_excessive_weight` | yes | yes | yes |
| GO-S-01 | `TestTransferAPI` (InsufficientBalance case) | yes | yes | yes |
| TS-S-02 | `PetService :: Create should reject a non-positive age` | yes | yes (exact name match) | yes |
| JAVA-S-01 | `UserServiceImplTest.saveRejectsBlankUsername` / `saveAcceptsNonBlankUsername` | yes (both discovered as changed_nodes) | yes, at class level (`UserServiceImplTest`) | yes |
| RS-S-01 | `tests::new_rejects_zero_size` | yes (discovered as a changed symbol, described in PR semantic analysis) | **no** — no obligation exists to map it to (affected_flows=0) | n/a |

This is raw inclusion per case, not a cross-case recall metric — each case has exactly one ground-truth test in this suite.

## Per-case notes

### PY-S-02
- Real voice routes reached correctly: `POST /audio/speech`, `POST /audio/voices/combine`, `POST /dev/captioned_speech`, all via `process_and_validate_voices`.
- No unrelated path. `unresolved_changed_symbols=0`.
- Matches expected PASS.

### GO-S-01
- `POST /transfers → Server.createTransfer → Server.checkSufficientBalance` intact, structurally proven.
- No regression observed from the symbol-identity/canonical-identity work — confirms the Rust-motivated `canonical_qualified_name` tier is purely additive for Go, which never populates `cbm_qualified_name` differently from its existing short form here.
- Matches expected PASS.

### TS-S-02
- `POST /pets` proven; `PetController.create → PetService.create` established through the deterministic `member_call_bridge` (`member_call_bridge_edges_added=14` in diagnostics).
- No false `POST /users`. The bridge also correctly found a second genuine consumer, `PetResolver.addPet` (also proven, verified against source in the prior implementation task).
- GT test discovered and mapped by exact name.
- Matches expected PASS.

### JAVA-S-01
- Genuine path `POST /user → UserController.save → IUserService.save → UserServiceImpl.save` intact and proven — the `interface_bridge` (`interface_bridge_edges_added=25`) correctly reaches it via `UserServiceImpl.save`'s canonical qualified name.
- **Known, unaddressed caveat, recorded honestly per instruction:** 7 of the 9 accepted impacts (`initData`, `addClientDetails`, `updateClientDetails`, `updateClientSecret`, `createUser`, `updatePassword`, `updateUser`) are CBM call-graph noise — Spring Data / inherited repository `save()`-shaped calls in unrelated demo modules get misattributed to the changed `UserServiceImpl.save` by CBM's own resolution (not a Sydes identity-matching bug; confirmed in a prior investigation and explicitly not touched here).
- GT test discovered (both changed test methods) and mapped at class granularity.
- Matches expected PASS — the genuine path is what defines this classification, distinct from the known noise.

### RS-S-01
- CBM's canonical qualified identity connects `upload → PasteId::new`: the accepted impact `POST /` is `proven`, with `changed_symbols: ["new"]` and evidence `calls:...src.main.upload`.
- No unrelated Rocket crate/file contamination — every file referenced across the whole result is scoped to `examples/pastebin/`.
- `affected_flows=0`, as expected/accepted — no deterministic Rust route recognizer exists to build an `EndpointCandidate` for the rich flow trace.
- Matches expected PARTIAL.

## Findings

**Expected behavior**
- All five cases resolved to the SHA-pinned Sydes version, in exactly one canonical run each, with no infrastructure retries needed this round.
- Four of five (Python, Go, TypeScript, Java) reach PASS-quality structural proof of their genuine path; Rust reaches PARTIAL as explicitly accepted.

**Surprising behavior**
- `http_entrypoints=0` for both TS-S-02 and RS-S-01 in the raw diagnostic counter, despite both cases genuinely having HTTP routes reached and proven — both rely entirely on the generic route-index bridge rather than CBM's own native HTTP-entrypoint classification. Not a defect for this rerun's purposes (the routes are still found and proven), but a metric that reads misleadingly on its own.
- Java's ground-truth test mapping is class-level (`UserServiceImplTest`), while Python/Go/TypeScript's mapping is function-level (the individual test name). Both changed test *methods* are still correctly discovered as `changed_nodes`.

**Known limitations (already documented, not new)**
- JAVA-S-01's 7-item CBM Spring-Data-proxy call-graph noise (see per-case notes).
- RS-S-01's `affected_flows=0` due to the absence of a deterministic Rust route recognizer.

**Newly discovered backlog items (canonical findings only — not fixed here)**
- None found in this rerun beyond the two known, already-documented limitations above. No new false positives, no new language gaps, no new bugs surfaced.

## Five-language support (post-canonical-rerun)

- Python: **PASS**
- Go: **PASS**
- Java: **PASS**
- TypeScript: **PASS**
- Rust: **PARTIAL**

Unchanged from the pre-rerun expectation — the canonical run did not contradict any classification.
