# Sydes manual calibration — v1

## Scope

- 15 preregistered manual cases
- Python, Go, TypeScript, Java, Rust
- simple / medium / hard
- one frozen Sydes SHA — [`256f4f9e5e09956d6014bf450f4462f616e826ce`](https://github.com/sydes-ai/sydes/releases/tag/v0.2.0-beta.1)

Each case was selected, ground-truthed, and frozen *before* being run through Sydes. Full case-by-case detail: [`results/simple-v1/`](simple-v1/), [`results/medium-v1/`](medium-v1/), [`results/hard-v1/`](hard-v1/).

## Results by complexity

| Complexity | Pass | Partial | Unsupported |
|---|---|---|---|
| Simple | 4 | 1 | 0 |
| Medium | 3 | 2 | 0 |
| Hard | 1 | 1 | 3 |

## Results by language

| Language | Simple | Medium | Hard |
|---|---|---|---|
| Python | Pass | Pass | Pass |
| Go | Pass | Partial | Unsupported |
| TypeScript | Pass | Pass | Unsupported |
| Java | Pass | Pass | Partial |
| Rust | Partial | Partial | Unsupported |

## What this shows

- Strongest support on conventional Python/Java paths.
- Good basic TypeScript/Go support.
- Capability degrades as propagation becomes more architectural.
- Async-consumer entrypoints remain limited.
- Deep backward CQRS propagation remains limited.
- Cross-cutting filters remain partial.
- Rust support remains experimental.

## Disclaimer

**This is a manual calibration suite, not an independent benchmark evaluation.** 15 cases do not establish statistical significance, and case selection was performed by the team building the tool.
