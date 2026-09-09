#!/usr/bin/env python3
"""Render a reviewer-facing Markdown PR comment from a Sydes result JSON.

Reads the machine-readable result written by `sydes verify-change --json` and
emits the comment body used for both the PR comment and the Actions job
summary.

DESIGN INTENT (read this before changing section order or wording):

The PR comment is a decision surface, not a metrics dump. It answers, in the
order a reviewer actually needs them: what changed, what system behavior it
reaches and through what logical path, how far Sydes could establish that
propagation, what's still unverified, and what (if anything) to check before
merging. Deep evidence -- full obligation lists, confidence scores, graph
diagnostics, the complete symbol table -- belongs in the uploaded JSON
artifact and (eventually) a dashboard, not here. A tiny, deliberately sparse
<details> block carries a few grounding facts; it is not a second render of
the whole result.

Canonical Sydes vocabulary (`VERIFICATION INCOMPLETE`, `obligation`,
`proven`/`inferred`, `unresolved`) is preserved everywhere in the underlying
JSON and is NEVER changed by this script. Only the human-facing Markdown
text translates it -- see _HUMAN_VERDICT / _HUMAN_RISK / the "Established"/
"Likely"/"Not fully traced" vocabulary below. The word "obligation" never
appears in rendered output.

Everything here is deterministic: no LLM calls, no network calls, and the
same input JSON always renders identically.

Usage:
    render_sydes_pr.py RESULT_JSON --out comment.md
                       [--diagnostics-out diagnostics.json] [--run-url URL]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

MARKER = "<!-- sydes-verification-comment -->"

# ---------------------------------------------------------------------------
# Canonical -> human vocabulary. Internal enums are never shown to a
# reviewer; only these translations are.
# ---------------------------------------------------------------------------

_HUMAN_VERDICT = {
    "VERIFIED": "Fully verified",
    "VERIFICATION INCOMPLETE": "More verification needed",
    "ACTION REQUIRED": "Action required",
    "OK": "No affected behavior found",
}

_HUMAN_RISK = {"LOW": "Low risk", "MEDIUM": "Medium risk", "HIGH": "High risk"}

_AREA_BY_BOUNDARY_KIND = {
    "api": "API",
    "callable": "Service logic",
    "async": "Background jobs",
    "external": "External integration",
    "unknown": "Other",
}

_OBLIGATION_KIND_LABEL = {
    "route_contract": "API contract",
    "validation": "Validation rule",
    "side_effect": "Side effect",
    "state_consistency": "State consistency",
    "event_emission": "Event emitted",
    "cross_repo_call": "Cross-service call",
}

_OBLIGATION_STATUS_LABEL = {
    "passed": "Verified",
    "failed": "Failed",
    "unverified": "Not yet run",
    "unknown": "Not fully traced",
}

# A large fraction of `VerificationObligation.statement` values are
# auto-generated route-contract boilerplate ("contract happy path", "POST
# /x responds 201 — Default 201 response skeleton.") with no reviewer value.
# Filtering these out, rather than rendering every obligation, is what keeps
# the Verification section from becoming another metrics dump.
_BOILERPLATE_STATEMENT_RE = re.compile(
    r"^contract happy path$|responds \d+ — Default \d+ response skeleton\.?$",
    re.IGNORECASE,
)

# Deterministic truncation limits. These are the renderer's entire
# "how much is too much" policy -- change them here, not ad hoc in a
# render function.
_MAX_ESTABLISHED_PATHS = 3
_MAX_LIKELY_PATHS = 2
_MAX_AREA_ROWS = 6
_MAX_CHECKLIST_ROWS = 4
_MAX_BEFORE_MERGE = 3
_MAX_DETAIL_SYMBOLS = 5


def _get(mapping: Any, *keys: str, default: Any = None) -> Any:
    """Walk nested dicts without assuming any level exists."""
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean(text: Any, limit: int = 240) -> str:
    """Collapse a model- or backend-authored string to one safe, bounded
    Markdown line. Shorter default limit than before: this script no longer
    renders long paragraphs outside the single `change_summary` line.

    Truncates at a word boundary -- cutting mid-word ("...stronger inpu…")
    reads as broken, not concise."""
    if not isinstance(text, str):
        return ""
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    truncated = flattened[: limit - 1]
    last_space = truncated.rfind(" ")
    if last_space > limit * 0.6:  # only back off to the word boundary if it's not too far short
        truncated = truncated[:last_space]
    return truncated.rstrip().rstrip(".,;:") + "…"


def _test_file_paths(result: dict[str, Any]) -> set[str]:
    """Paths whose file role marks them as tests, for the production split."""
    paths: set[str] = set()
    for item in _as_list(_get(result, "change", "files", default=[])):
        role = str(_get(item, "role", default="") or "")
        path = _get(item, "path", default="")
        if path and "test" in role.lower():
            paths.add(str(path))
    return paths


#: `analysis_notes` is a flat list mixing genuinely different concerns --
#: structural/route-discovery notes, and separately, provider-availability
#: notes (a missing API key, an LLM call failing) -- with no type tag to
#: tell them apart programmatically. Blindly picking the first note can
#: surface "OPENAI_API_KEY is not set" as if it explained why no system
#: path was found, which is misleading when a real structural note (e.g.
#: "No discovered route declaration reaches the changed symbols.") is
#: also present later in the same list.
_PROVIDER_NOTE_MARKERS = ("api_key", "provider", "code review was requested")


def _pick_analysis_note(result: dict[str, Any], limit: int = 200) -> str:
    """The single most reviewer-relevant analysis note, if any: prefers a
    structural note over a provider-availability one, but still returns a
    provider note rather than nothing if that's all there is."""
    notes = [_clean(n, limit=limit) for n in _as_list(_get(result, "analysis_notes", default=[]))]
    notes = [n for n in notes if n]
    if not notes:
        return ""
    structural = [n for n in notes if not any(m in n.lower() for m in _PROVIDER_NOTE_MARKERS)]
    return structural[0] if structural else notes[0]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def render_header(result: dict[str, Any], lines: list[str]) -> None:
    verdict = str(_get(result, "summary", "verdict", default="UNKNOWN"))
    risk = str(_get(result, "summary", "risk", default="UNKNOWN"))
    human_verdict = _HUMAN_VERDICT.get(verdict, verdict.capitalize())
    human_risk = _HUMAN_RISK.get(risk, risk.capitalize() + " risk" if risk != "UNKNOWN" else "Risk unknown")

    lines.append("## Sydes")
    lines.append("")
    lines.append(f"**{human_verdict}** · {human_risk}")
    lines.append("")


# ---------------------------------------------------------------------------
# What changed
# ---------------------------------------------------------------------------


def render_change(result: dict[str, Any], lines: list[str]) -> None:
    """One grounded, plain-English paragraph. No confidence numbers, no
    per-behavior-change bullet list here -- individual behavior changes
    that matter are what System impact exists to show, with an actual
    path attached, not a restated sentence."""
    summary = _clean(_get(result, "pr_semantic_analysis", "change_summary", default=""), limit=600)
    if not summary:
        return
    lines.append("### What changed")
    lines.append("")
    lines.append(summary)
    lines.append("")


# ---------------------------------------------------------------------------
# System impact -- the centerpiece.
# ---------------------------------------------------------------------------


def _boundary_status(boundary: dict[str, Any]) -> str:
    return str(_get(boundary, "status", default="proven"))


# A raw CBM-style qualified identifier (a repo-path-prefixed dotted symbol
# name used internally for identity matching) occasionally ends up as a
# boundary's only `label` when no better human description was available.
# It is never meant for display -- e.g.
# "home-runner-work-Rocket-Rocket.examples.todo.src.main.delete" -- so
# detect that shape and fall back to the boundary's own `symbol` field,
# which is always a plain, short name.
_RAW_IDENTIFIER_LABEL_RE = re.compile(r"[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+){3,}$")


def _boundary_display_label(boundary: dict[str, Any]) -> str:
    label = _clean(_get(boundary, "label", default=""), limit=90)
    if label and not _RAW_IDENTIFIER_LABEL_RE.match(label.replace(" ", "")):
        return label
    symbol = str(_get(boundary, "symbol", default="") or "").strip()
    if symbol:
        return f"`{symbol}`"
    return label or "Affected"


def summarize_system_impact_areas(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Group `affected_boundaries` (and, when present, `runtime_dependencies`)
    into a small `(area, impact description)` table using only the kind/
    subtype classification the backend already assigns -- no new categories
    are invented, and an area with no real boundary in it is never shown."""
    boundaries = _as_list(_get(result, "affected_boundaries", default=[]))
    by_area: dict[str, list[dict[str, Any]]] = {}
    for b in boundaries:
        area = _AREA_BY_BOUNDARY_KIND.get(str(_get(b, "kind", default="unknown")), "Other")
        by_area.setdefault(area, []).append(b)

    rows: list[tuple[str, str]] = []
    for area, items in by_area.items():
        established = [b for b in items if _boundary_status(b) == "proven"]
        likely = [b for b in items if _boundary_status(b) != "proven"]
        if len(items) == 1:
            label = _boundary_display_label(items[0])
            qualifier = "established" if established else "likely, not fully established"
            rows.append((area, f"{label} ({qualifier})"))
        else:
            parts = []
            if established:
                parts.append(f"{len(established)} established")
            if likely:
                parts.append(f"{len(likely)} likely")
            rows.append((area, ", ".join(parts) or f"{len(items)} affected"))

    # Fallback: some backends/changes populate affected_flows without ever
    # populating affected_boundaries. Rather than showing an empty System
    # impact section when real flow data exists, summarize flows into a
    # single API row -- still grounded, never invented.
    if not rows:
        flows = _as_list(_get(result, "affected_flows", default=[]))
        if flows:
            rows.append(("API", f"{len(flows)} route(s) affected"))

    deps = _as_list(_get(result, "runtime_dependencies", default=[]))
    if deps:
        names = [str(_get(d, "name", default="")) for d in deps if _get(d, "name", default="")]
        names = list(dict.fromkeys(names))  # dedupe, keep order
        if names:
            rows.append(("Infrastructure", ", ".join(names[:5])))

    return rows[:_MAX_AREA_ROWS]


def _flow_path_label(flow: dict[str, Any], test_paths: set[str]) -> str:
    """Build a route -> handler -> changed-symbol label for one affected
    flow -- the concrete, reviewer-legible form of "what this change
    reaches", e.g. `POST /pets` -> `PetController.create` -> `PetService.create`.

    The changed symbol shown must be a PRODUCTION symbol, not a test: a
    flow's `changed_nodes` mixes the production symbol(s) actually changed
    with any newly-added/updated test functions, in diff order rather than
    call-depth order. When more than one production symbol is present, the
    LAST one is shown -- in practice the deeper, service-layer symbol
    rather than a controller-level symbol already shown as the handler. If
    no production symbol exists beyond the handler itself, the path is
    left at route -> handler with no third segment."""
    parts = [str(_get(flow, "entry_label", default="") or "").strip()]
    handler = str(_get(flow, "handler", default="") or "").strip()
    if handler and handler != parts[0]:
        parts.append(handler)
    changed = _as_list(_get(flow, "changed_nodes", default=[]))
    production_symbol = ""
    for node in changed:
        symbol = str(_get(node, "symbol", default="") or "").strip()
        if not symbol or symbol == handler:
            continue
        file_path = str(_get(node, "file", default="") or "")
        if file_path not in test_paths:
            production_symbol = symbol  # keep overwriting -- last one wins
    if production_symbol:
        parts.append(production_symbol)
    return parts


def select_representative_paths(
    result: dict[str, Any],
) -> tuple[list[list[str]], list[str], int, int]:
    """Deterministic representative-path selection -- the rule that keeps a
    20-route change from dumping 20 paths into the comment.

    Returns (established_paths, likely_labels, established_remaining,
    likely_remaining). `established_paths` are route->handler->symbol part
    lists (for the fenced/tree rendering); `likely_labels` are plain
    strings (inferred impacts rarely have a full traced chain to show)."""
    flows = _as_list(_get(result, "affected_flows", default=[]))
    impacts = _as_list(_get(result, "accepted_impacts", default=[]))
    impact_status_by_id = {
        str(_get(imp, "id", default="")): str(_get(imp, "status", default="")) for imp in impacts
    }
    test_paths = _test_file_paths(result)

    established_all: list[list[str]] = []
    likely_all: list[str] = []
    shown_impact_ids: set[str] = set()

    for flow in flows:
        parts = _flow_path_label(flow, test_paths)
        if not parts or not parts[0]:
            continue
        flow_id = str(_get(flow, "id", default=""))
        shown_impact_ids.add(flow_id)
        status = impact_status_by_id.get(flow_id, "proven")
        if status == "proven":
            established_all.append(parts)
        else:
            likely_all.append(" → ".join(parts))

    for impact in impacts:
        if str(_get(impact, "id", default="")) in shown_impact_ids:
            continue
        if str(_get(impact, "status", default="")) != "inferred":
            continue
        label = _clean(_get(impact, "behavior_label", default=""), limit=100) or _clean(
            _get(impact, "label", default=""), limit=100
        )
        if label:
            likely_all.append(label)

    established = established_all[:_MAX_ESTABLISHED_PATHS]
    likely = likely_all[:_MAX_LIKELY_PATHS]
    return (
        established,
        likely,
        max(0, len(established_all) - len(established)),
        max(0, len(likely_all) - len(likely)),
    )


def render_system_impact(result: dict[str, Any], lines: list[str]) -> None:
    """The section a reviewer actually needs: what area of the system this
    reaches, and through what logical path -- not aggregate counts."""
    lines.append("### System impact")
    lines.append("")

    area_rows = summarize_system_impact_areas(result)
    if area_rows:
        lines.append("| Area | Impact |")
        lines.append("| --- | --- |")
        for area, impact in area_rows:
            lines.append(f"| {area} | {impact} |")
        lines.append("")

    established, likely, established_more, likely_more = select_representative_paths(result)

    if not established and not likely:
        # Nothing resolved at all -- this must never read as "nothing is
        # affected". Say plainly that tracing did not reach anything, and
        # cite the real reason when one is available.
        reason = _pick_analysis_note(result, limit=160)
        lines.append(
            "Sydes could not establish a system path from the changed code to any "
            "entrypoint for this change."
        )
        if reason:
            lines.append(f"_{reason}_")
        lines.append("")
        return

    if established:
        lines.append("**Established**")
        lines.append("")
        for parts in established:
            if len(parts) > 1:
                lines.append("```text")
                lines.append(parts[0])
                for p in parts[1:]:
                    lines.append(f"  → {p}")
                lines.append("```")
                lines.append("")  # blank line between fences -- otherwise adjacent
                                   # ```text blocks can render as one merged block
            else:
                lines.append(f"- `{parts[0]}`")
        if established_more:
            lines.append(f"_…and {established_more} more established path(s) in the full result._")
        lines.append("")

    if likely:
        lines.append("**Likely, not fully established**")
        lines.append("")
        for label in likely:
            lines.append(f"- {label}")
        if likely_more:
            lines.append(f"_…and {likely_more} more likely impact(s) in the full result._")
        lines.append("")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


#: `kind == "side_effect"` obligations are generated from the template
#: "{route} accessed {raw source expression}" -- confirmed across every
#: language and case inspected (Go, Java, Rust, TypeScript all follow it
#: exactly). The statement is a literal code fragment BY CONSTRUCTION, not
#: sometimes; there is no clean-vs-messy split within this kind to detect,
#: so it is excluded entirely rather than truncated into a half-cut
#: snippet. This is a data-shape observation, not a semantic judgment
#: about side effects being unimportant -- see the module docstring's
#: scope note: rendering can't parse code to produce a clean claim, and
#: showing a raw fragment reads worse than omitting it.
_CODE_FRAGMENT_OBLIGATION_KINDS = {"side_effect"}


def _real_statement_obligations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Obligations with a real, specific, reviewer-legible statement --
    filtering out both the generic route-contract boilerplate ("contract
    happy path", "responds 201 — Default 201 response skeleton.") and the
    code-fragment-by-construction kinds (see
    `_CODE_FRAGMENT_OBLIGATION_KINDS`). Deduplicated by (kind, statement)
    since the same generic-shaped claim can otherwise repeat once per
    flow."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for flow in _as_list(_get(result, "affected_flows", default=[])):
        for obligation in _as_list(_get(flow, "obligations", default=[])):
            kind = str(_get(obligation, "kind", default=""))
            if kind in _CODE_FRAGMENT_OBLIGATION_KINDS:
                continue
            statement = str(_get(obligation, "statement", default="") or "").strip()
            if not statement or _BOILERPLATE_STATEMENT_RE.search(statement):
                continue
            key = (kind, statement[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(obligation)
    return out


def _meaningful_obligations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The obligations worth showing a reviewer at all.

    `VerificationObligation.introduced_by_change` is the backend's own
    signal for "this claim exists specifically because of this diff" as
    opposed to a pre-existing, generic obligation on the same route (e.g. a
    change to pause-duration validation does not make an unrelated
    `allow_voice_tags` route check something THIS PR needs verifying). When
    that flag is populated for this result, trust it completely and show
    only those. It is not always populated by every analysis path, though
    (confirmed empirically: several real results have zero obligations
    flagged `introduced_by_change=True` despite having real, specific
    statements) -- in that case, fall back to every real (non-boilerplate)
    statement, on the honest assumption that an unpopulated flag is a data
    gap, not a claim that nothing here relates to the change."""
    real = _real_statement_obligations(result)
    introduced = [o for o in real if _get(o, "introduced_by_change", default=False)]
    return introduced if introduced else real


def render_verification(result: dict[str, Any], lines: list[str]) -> None:
    """Human questions/status, not internal counters. Rows are only added
    when the data supports them -- an empty checklist with just the two
    always-known test lines is a correct, honest render, not a bug."""
    counts = _get(result, "summary", "counts", default={})
    meaningful = _meaningful_obligations(result)[:_MAX_CHECKLIST_ROWS]

    lines.append("### Verification")
    lines.append("")
    lines.append("| Check | Status |")
    lines.append("| --- | --- |")
    for obligation in meaningful:
        kind_label = _OBLIGATION_KIND_LABEL.get(str(_get(obligation, "kind", default="")), "")
        statement = _clean(_get(obligation, "statement", default=""), limit=100)
        check = f"**{kind_label}:** {statement}" if kind_label else statement
        status = _OBLIGATION_STATUS_LABEL.get(str(_get(obligation, "status", default="")), "Not fully traced")
        lines.append(f"| {check} | {status} |")

    mapped_tests = counts.get("mapped_tests", 0)
    tests_row = "None" if mapped_tests == 0 else str(mapped_tests)
    lines.append(f"| Relevant tests | {tests_row} |")

    executed = counts.get("tests_executed", 0)
    # "Not run" is a deliberate, quiet phrasing for the common --no-run-tests
    # case -- it must never read as a failure.
    executed_label = "Not run" if executed == 0 else f"{executed} run"
    lines.append(f"| Tests executed by Sydes | {executed_label} |")
    lines.append("")


# ---------------------------------------------------------------------------
# Before merge
# ---------------------------------------------------------------------------


def render_before_merge(result: dict[str, Any], lines: list[str]) -> None:
    """Only rendered when there is a concrete, evidence-based action to
    suggest -- an unverified/unknown/failed obligation with a real
    statement. Never fabricated, and omitted entirely (not padded) when
    there's nothing concrete to say."""
    meaningful = _meaningful_obligations(result)
    actionable = [o for o in meaningful if str(_get(o, "status", default="")) != "passed"]
    if not actionable:
        return

    lines.append("### Before merge")
    lines.append("")
    for obligation in actionable[:_MAX_BEFORE_MERGE]:
        statement = _clean(_get(obligation, "statement", default=""), limit=140)
        lines.append(f"- Verify: {statement}")
    lines.append("")


# ---------------------------------------------------------------------------
# Code review -- status/count only. Detailed findings are a different
# product surface (inline comments / full result), never duplicated here.
# ---------------------------------------------------------------------------


def render_review(result: dict[str, Any], lines: list[str]) -> None:
    """`code_findings` being empty means something different depending on
    `code_review_status` -- the pass never ran, it ran and failed, or it
    ran and genuinely found nothing -- and only the status field can tell
    those apart. Rendering "no findings" for a review that never actually
    completed would be absence of evidence read as evidence of absence."""
    status = _get(result, "code_review_status")
    findings = _as_list(_get(result, "code_findings", default=[]))
    if status is None:
        if not findings:
            return
        status = "completed"

    if status == "not_requested":
        return

    lines.append("### Code review")
    lines.append("")

    if status == "unavailable":
        lines.append("Code review unavailable — the provider could not complete the analysis.")
        lines.append("")
        return

    if not findings:
        lines.append("No findings.")
        lines.append("")
        return

    severities = [str(_get(f, "severity", default="P3")) for f in findings]
    high = sum(1 for s in severities if s in ("P0", "P1"))
    low = len(findings) - high
    parts = []
    if high:
        parts.append(f"{high} higher-priority")
    if low:
        parts.append(f"{low} lower-priority")
    lines.append(f"{len(findings)} finding(s) ({', '.join(parts)}) — see the full result for detail.")
    lines.append("")


# ---------------------------------------------------------------------------
# Optional, deliberately tiny technical-evidence block. NOT a second render
# of the whole result -- see module docstring.
# ---------------------------------------------------------------------------


def render_details(result: dict[str, Any], lines: list[str]) -> None:
    body: list[str] = []

    symbols = _as_list(_get(result, "change", "symbols", default=[]))
    test_paths = _test_file_paths(result)
    production_symbols = [
        s for s in symbols if str(_get(s, "file", default="")) not in test_paths
    ]
    if production_symbols:
        names = [str(_get(s, "name", default="")) for s in production_symbols[:_MAX_DETAIL_SYMBOLS] if _get(s, "name", default="")]
        if names:
            more = len(production_symbols) - len(names)
            line = "**Changed symbols:** " + ", ".join(f"`{n}`" for n in names)
            if more > 0:
                line += f" (+{more} more)"
            body.append(line)

    coverage_note = _pick_analysis_note(result, limit=200)
    if coverage_note:
        body.append(f"**Coverage limit:** {coverage_note}")

    deps = _as_list(_get(result, "runtime_dependencies", default=[]))
    if deps:
        name = _get(deps[0], "name", default="")
        if name:
            body.append(f"**Key dependency:** {name}")

    if not body:
        return

    lines.append("<details><summary>Technical evidence</summary>")
    lines.append("")
    for item in body:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("</details>")
    lines.append("")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def render_footer(lines: list[str], run_url: str | None) -> None:
    lines.append("---")
    footer = "Sydes"
    if run_url:
        footer += f" · [View full analysis]({run_url}) · [View run]({run_url})"
    lines.append(footer)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def render(result: dict[str, Any], run_url: str | None = None) -> str:
    lines: list[str] = [MARKER, ""]
    render_header(result, lines)
    render_change(result, lines)
    render_system_impact(result, lines)
    render_verification(result, lines)
    render_before_merge(result, lines)
    render_review(result, lines)
    render_details(result, lines)
    render_footer(lines, run_url)
    return "\n".join(lines).rstrip() + "\n"


def render_unavailable(reason: str, run_url: str | None = None) -> str:
    """Fallback body when there is no result to read — a failed or partial
    run should still leave the reviewer with an explanation rather than
    silence."""
    lines = [
        MARKER,
        "",
        "## Sydes",
        "",
        f"**No result produced** — {reason}",
        "",
        "This does not indicate a verdict about the change. See the run log for details.",
        "",
    ]
    render_footer(lines, run_url)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Sydes result as Markdown.")
    parser.add_argument("result", type=Path, help="Path to sydes-result.json")
    parser.add_argument("--out", type=Path, required=True, help="Markdown output path")
    parser.add_argument("--diagnostics-out", type=Path, help="Write diagnostics to this JSON path")
    parser.add_argument("--run-url", default=None, help="Actions run URL for the footer link")
    args = parser.parse_args()

    result: dict[str, Any] | None = None
    reason = ""
    try:
        loaded = json.loads(args.result.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            result = loaded
        else:
            reason = "the result file did not contain a JSON object"
    except FileNotFoundError:
        reason = "no result file was written"
    except (OSError, json.JSONDecodeError) as exc:
        reason = f"the result file could not be read ({exc})"

    if result is None:
        args.out.write_text(render_unavailable(reason, args.run_url), encoding="utf-8")
        print(f"Sydes result unavailable: {reason}")
        return 0

    args.out.write_text(render(result, args.run_url), encoding="utf-8")
    print(f"Rendered Sydes comment to {args.out}")

    # Diagnostics are split out here rather than in Sydes itself: the result
    # schema still carries them, and this keeps the split to the presentation
    # layer. Real schema separation belongs in Sydes later.
    if args.diagnostics_out:
        payload = {
            "generated_at": result.get("generated_at"),
            "diagnostics": _as_list(result.get("diagnostics")),
            "notes": _as_list(result.get("notes")),
            "analysis_notes": _as_list(result.get("analysis_notes")),
        }
        args.diagnostics_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote diagnostics to {args.diagnostics_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
