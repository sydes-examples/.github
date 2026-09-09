# Manual calibration suite — public summary (v1)

## Scope

15 manually preregistered calibration cases: one simple, one medium, and
one hard complexity case per language (Python, Go, TypeScript, Java,
Rust). Each case was selected, ground-truthed, and frozen *before* being
run through Sydes — never tuned after seeing a result. All 15 ran against
one frozen Sydes SHA (`256f4f9e5e09956d6014bf450f4462f616e826ce`, the
engine validated for the [v0.2.0-beta.1 release](https://github.com/sydes-ai/sydes/releases/tag/v0.2.0-beta.1)).

Full case-by-case detail: [`results/simple-v1/`](simple-v1/),
[`results/medium-v1/`](medium-v1/), [`results/hard-v1/`](hard-v1/).
Preregistrations: [`examples/simple-v1/`](../examples/README.md),
[`examples/medium-v1/`](../examples/medium-v1/),
[`examples/hard-v1/`](../examples/hard-v1/).

## Results by complexity

| Band | PASS | PARTIAL | Unsupported |
|---|---|---|---|
| Simple | 4 | 1 | 0 |
| Medium | 3 | 2 | 0 |
| Hard | 1 | 1 | 3 |

## Results by language

| Language | Simple | Medium | Hard |
|---|---|---|---|
| Python | PASS | PASS | PASS |
| Go | PASS | PARTIAL | Unsupported |
| TypeScript | PASS | PASS | Unsupported |
| Java | PASS | PASS | PARTIAL |
| Rust | PARTIAL | PARTIAL | Unsupported |

## What we learned

- **Support degrades honestly with structural complexity**, in every
  language — no language holds a clean PASS all the way to the hard tier
  except Python, whose hard case stayed within a single, deterministic,
  non-async chain.
- **Async/task-queue entrypoints remain a gap.** A non-HTTP consumer (a
  task-queue handler with no HTTP path at all) was not represented in
  Sydes' entrypoint model at all — confirmed directly in the Go hard case.
- **Deep backward CQRS propagation remains a gap.** Tracing forward from a
  controller through a command-bus dispatch to a handler works; tracing
  backward from a deeply nested value object up through an aggregate and
  a command handler to its controller does not yet, confirmed in the
  TypeScript hard case.
- **Cross-cutting filter semantics remain partial.** A shared
  authentication filter affecting every route in a module could only be
  proven for one concretely-reachable route, not represented as a
  class-wide concern — confirmed in the Java hard case.
- **Rust route-framework support remains experimental**, confirmed across
  two different frameworks (Rocket and Axum) with two different failure
  shapes: false positives from cross-crate name matching, and a complete
  absence of route detection.

## Disclaimer

**This is a manual calibration suite, not an independent benchmark
evaluation.** 15 cases do not establish statistical significance. Case
selection — while preregistered before observation, and adversarial where
possible — was performed by the team building the tool. Treat these
results as a calibration signal about where Sydes currently stands, not a
guarantee about any other codebase or change.
