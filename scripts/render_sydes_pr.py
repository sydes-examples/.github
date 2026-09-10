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

#: Verification is reported per high-level category, never per raw obligation
#: statement (see `render_verification`) -- these are the only categories
#: shown, in this fixed display order. `side_effect` has no entry: it is
#: excluded everywhere obligations are read (see
#: `_CODE_FRAGMENT_OBLIGATION_KINDS`).
_OBLIGATION_CATEGORY_LABEL = {
    "route_contract": "API behavior",
    "validation": "Validation behavior",
    "cross_repo_call": "Cross-service behavior",
    "state_consistency": "State consistency",
    "event_emission": "Event emission",
}
_OBLIGATION_CATEGORY_ORDER = [
    "route_contract",
    "validation",
    "cross_repo_call",
    "state_consistency",
    "event_emission",
]

_OBLIGATION_STATUS_LABEL = {
    "passed": "Verified",
    "failed": "Failed",
    "unverified": "Not yet run",
    "unknown": "Not fully traced",
}

#: When a category has more than one obligation, show the worst status
#: across the group (a reviewer needs to know the worst case, not an
#: arbitrary one) -- lower rank wins.
_OBLIGATION_STATUS_RANK = {"failed": 0, "unverified": 1, "unknown": 2, "passed": 3}

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


def _impact_status_by_id(result: dict[str, Any]) -> dict[str, str]:
    impacts = _as_list(_get(result, "accepted_impacts", default=[]))
    return {str(_get(imp, "id", default="")): str(_get(imp, "status", default="")) for imp in impacts}


def _flow_fallback_status(flow: dict[str, Any]) -> str:
    """A flow's OWN `impact_status` field, used only when no
    `accepted_impacts` entry matches this flow's id at all.

    The fallback must never be a hardcoded "proven": that would render a
    flow explicitly marked non-proven (e.g. `impact_status="inferred"`) as
    Established the moment its accepted_impacts entry happens to be
    missing -- a real internal-consistency break (see task item 7), not a
    theoretical one. `AffectedFlow.impact_status` already carries this
    same "proven" default in the canonical model itself, so trusting it
    here changes nothing for the ordinary, fully-populated case and only
    fixes the case where the two collections disagree."""
    return str(_get(flow, "impact_status", default="proven") or "proven")


def _flow_routes_by_status(
    result: dict[str, Any], impact_status_by_id: dict[str, str]
) -> tuple[list[str], list[str]]:
    """All flow entry routes (e.g. `POST /users`), split into established vs
    likely using the same `accepted_impacts` cross-reference used for the
    representative-path rendering below -- deduped, in flow order."""
    established: list[str] = []
    likely: list[str] = []
    seen: set[str] = set()
    for flow in _as_list(_get(result, "affected_flows", default=[])):
        route = str(_get(flow, "entry_label", default="") or "").strip()
        if not route or route in seen:
            continue
        seen.add(route)
        status = impact_status_by_id.get(str(_get(flow, "id", default="")), _flow_fallback_status(flow))
        (established if status == "proven" else likely).append(route)
    return established, likely


def _route_impact_row(established_routes: list[str], likely_routes: list[str]) -> tuple[str, str] | None:
    """A concrete, descriptive 'API' row -- never a bare established/likely
    count. One or two routes are named directly; three or more collapse to
    a count (still a route count, not an internal analysis-state count)."""
    parts: list[str] = []
    if established_routes:
        if len(established_routes) == 1:
            parts.append(f"`{established_routes[0]}` impact established")
        elif len(established_routes) == 2:
            parts.append(f"`{established_routes[0]}` and `{established_routes[1]}` impact established")
        else:
            parts.append(f"{len(established_routes)} API routes affected (established)")
    if likely_routes:
        if len(likely_routes) == 1:
            parts.append(f"`{likely_routes[0]}` likely affected, not fully traced")
        else:
            parts.append(f"{len(likely_routes)} more API routes likely affected, not fully traced")
    return ("API", "; ".join(parts)) if parts else None


def _boundary_groups_by_kind(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for b in _as_list(_get(result, "affected_boundaries", default=[])):
        by_kind.setdefault(str(_get(b, "kind", default="unknown")), []).append(b)
    return by_kind


def _describe_group(items: list[dict[str, Any]]) -> str:
    """Describe one area's boundaries using their own label/status fields --
    concrete for one item, still descriptive (never a bare count alone) for
    two, and only falling back to a count when a group is large enough that
    naming each one would be noise."""
    established = [b for b in items if _boundary_status(b) == "proven"]
    likely = [b for b in items if _boundary_status(b) != "proven"]
    if len(items) == 1:
        qualifier = "established" if established else "likely, not fully established"
        return f"{_boundary_display_label(items[0])} ({qualifier})"
    parts: list[str] = []
    if established:
        if len(established) == 1:
            parts.append(f"{_boundary_display_label(established[0])} (established)")
        else:
            parts.append(f"{len(established)} established")
    if likely:
        if len(likely) == 1:
            parts.append(f"{_boundary_display_label(likely[0])} (not fully traced)")
        else:
            parts.append(f"{len(likely)} not fully traced")
    return "; ".join(parts)


def _infrastructure_row(result: dict[str, Any]) -> tuple[str, str] | None:
    """Only dependencies `runtime_dependencies` itself ties to the affected
    flow (`scope == "affected_flow"`) are shown at the top level -- a
    repository-wide dependency (`scope == "repository"`) was merely detected
    somewhere in the codebase and says nothing about this change, so it is
    dropped here rather than dumped as noise. This reads an existing field;
    it does not change how runtime dependency analysis itself works."""
    deps = _as_list(_get(result, "runtime_dependencies", default=[]))
    flow_scoped = [d for d in deps if _get(d, "scope", default="") == "affected_flow"]
    names = list(dict.fromkeys(str(_get(d, "name", default="")) for d in flow_scoped if _get(d, "name", default="")))
    if not names:
        return None
    verb = "participates" if len(names) == 1 else "participate"
    return ("Infrastructure", f"{', '.join(names)} {verb} in the changed behavior")


def _system_impact_data(
    result: dict[str, Any],
) -> tuple[list[tuple[str, str]], list[str], bool]:
    """The single source of truth for 'what did Sydes find' -- shared by the
    System impact table and the Before-merge rules below so the two never
    disagree. Returns (area rows, area names flagged as an unresolved wider
    surface, whether any real impact signal exists at all)."""
    impact_status_by_id = _impact_status_by_id(result)
    established_routes, likely_routes = _flow_routes_by_status(result, impact_status_by_id)
    flow_files: set[str] = set()
    for flow in _as_list(_get(result, "affected_flows", default=[])):
        refs = _get(flow, "artifact_refs", default={})
        for key in ("route_file", "handler_file"):
            f = _get(refs, key, default="") if isinstance(refs, dict) else ""
            if f:
                flow_files.add(str(f))
        flow_file = _get(flow, "file", default="")
        if flow_file:
            flow_files.add(str(flow_file))

    by_kind = _boundary_groups_by_kind(result)
    api_boundaries = by_kind.pop("api", [])

    rows: list[tuple[str, str]] = []
    wider_areas: list[str] = []

    route_row = _route_impact_row(established_routes, likely_routes)
    if route_row:
        rows.append(route_row)
        # An `api`-kind boundary whose own source file is not one of the
        # traced routes' files is a genuinely separate signal -- e.g. a
        # shared auth filter the traced route passes through that also
        # gates other, untraced routes. It must never be folded into the
        # route count above (that would either overcount or hide it).
        #
        # Only worth checking at all when there is more than one distinct
        # api boundary: with exactly one, it IS the boundary behind the
        # route row above -- there is nothing "wider" to split out, and a
        # mismatched file (route discovery can mis-locate a route file,
        # e.g. a same-named handler in an unrelated example/crate) would
        # otherwise duplicate that single boundary as a second, bogus row.
        if len(api_boundaries) > 1:
            extra = [b for b in api_boundaries if str(_get(b, "file", default="")).strip() not in flow_files]
            if extra:
                area = "Wider API surface"
                rows.append((area, _describe_group(extra)))
                wider_areas.append(area)
    elif api_boundaries:
        # No flow data at all for this change -- describe the api
        # boundaries directly, same as any other kind below.
        rows.append(("API", _describe_group(api_boundaries)))

    for kind, items in by_kind.items():
        if items:
            rows.append((_AREA_BY_BOUNDARY_KIND.get(kind, "Other"), _describe_group(items)))

    has_any_impact = bool(established_routes or likely_routes or api_boundaries or any(by_kind.values()))

    infra = _infrastructure_row(result)
    if infra:
        rows.append(infra)

    return rows[:_MAX_AREA_ROWS], wider_areas, has_any_impact


def summarize_system_impact_areas(result: dict[str, Any]) -> list[tuple[str, str]]:
    rows, _wider_areas, _has_any_impact = _system_impact_data(result)
    return rows


#: Cap on distinct changed-target terminals shown per established flow (see
#: `_flow_changed_terminals`) -- keeps a flow that touches many files from
#: turning one route's box into a symbol dump, while still surfacing more
#: than one genuinely distinct established behavior instead of silently
#: collapsing to an arbitrary single pick.
_MAX_FLOW_TERMINALS = 3


def _flow_changed_terminals(flow: dict[str, Any], test_paths: set[str], handler: str) -> list[str]:
    """The changed PRODUCTION symbol(s) this flow's evidence actually
    reaches, one per distinct file among `changed_nodes`.

    A flow's `changed_nodes` mixes every production symbol touched with any
    newly-added/updated test functions, in diff/graph order rather than
    call-depth order -- test symbols are dropped via `test_paths`, same as
    before. Multiple changed symbols in the SAME file are, in practice,
    almost always part of one underlying edit (a helper extracted from, or
    called by, the symbol next to it) -- so at most one representative
    symbol is kept per file (the last one encountered), which naturally
    collapses that case to a single terminal without needing to understand
    the edit semantically. Symbols in DIFFERENT files are genuinely
    separate changed locations and are never merged: this is what lets a
    flow that reaches two unrelated fixes (e.g. a normalizer fix and an
    unrelated voice-loading fix) show both instead of silently keeping only
    one. Order of the returned list follows first-appearance order of each
    file in `changed_nodes`; the caller caps how many are actually shown."""
    changed = _as_list(_get(flow, "changed_nodes", default=[]))
    symbol_by_file: dict[str, str] = {}
    file_order: list[str] = []
    for node in changed:
        symbol = str(_get(node, "symbol", default="") or "").strip()
        if not symbol or symbol == handler:
            continue
        file_path = str(_get(node, "file", default="") or "")
        if file_path in test_paths:
            continue
        if file_path not in symbol_by_file:
            file_order.append(file_path)
        symbol_by_file[file_path] = symbol  # keep overwriting -- last one in this file wins
    return [symbol_by_file[f] for f in file_order]


def _flow_path_label(flow: dict[str, Any], test_paths: set[str]) -> tuple[list[str], int]:
    """Build a route -> handler -> changed-target(s) label for one affected
    flow -- the concrete, reviewer-legible form of "what this change
    reaches", e.g. `POST /pets` -> `PetController.create` -> `PetService.create`.

    Returns (parts, omitted_terminal_count). `parts` holds the route and
    handler followed by up to `_MAX_FLOW_TERMINALS` changed-target
    terminals (see `_flow_changed_terminals`) -- almost always one, but
    more than one when this flow's own evidence genuinely reaches changed
    symbols in more than one file. If no production symbol exists beyond
    the handler itself, the path is left at route -> handler with no
    further segment."""
    parts = [str(_get(flow, "entry_label", default="") or "").strip()]
    handler = str(_get(flow, "handler", default="") or "").strip()
    if handler and handler != parts[0]:
        parts.append(handler)
    terminals = _flow_changed_terminals(flow, test_paths, handler)
    parts.extend(terminals[:_MAX_FLOW_TERMINALS])
    return parts, max(0, len(terminals) - _MAX_FLOW_TERMINALS)


def select_representative_paths(
    result: dict[str, Any],
) -> tuple[list[tuple[list[str], int]], list[str], int, int]:
    """Deterministic representative-path selection -- the rule that keeps a
    20-route change from dumping 20 paths into the comment.

    Returns (established_paths, likely_labels, established_remaining,
    likely_remaining). `established_paths` are (parts, omitted_terminal_count)
    pairs -- `parts` is a route->handler->target(s) list for the
    fenced/tree rendering, `omitted_terminal_count` is how many further
    distinct changed-target terminals this same flow had beyond what
    `_flow_path_label` already kept (see `_MAX_FLOW_TERMINALS`).
    `likely_labels` are plain strings (inferred impacts rarely have a full
    traced chain to show)."""
    flows = _as_list(_get(result, "affected_flows", default=[]))
    impacts = _as_list(_get(result, "accepted_impacts", default=[]))
    impact_status_by_id = _impact_status_by_id(result)
    test_paths = _test_file_paths(result)

    established_all: list[tuple[list[str], int]] = []
    likely_all: list[str] = []
    shown_impact_ids: set[str] = set()

    for flow in flows:
        parts, omitted = _flow_path_label(flow, test_paths)
        if not parts or not parts[0]:
            continue
        flow_id = str(_get(flow, "id", default=""))
        shown_impact_ids.add(flow_id)
        status = impact_status_by_id.get(flow_id, _flow_fallback_status(flow))
        if status == "proven":
            established_all.append((parts, omitted))
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
        lines.append("| Area | Sydes found |")
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
        for idx, (parts, omitted_terminals) in enumerate(established):
            if len(parts) > 1:
                lines.append("```text")
                lines.append(parts[0])
                for p in parts[1:]:
                    lines.append(f"  → {p}")
                if omitted_terminals:
                    lines.append(f"  … +{omitted_terminals} more changed target(s)")
                lines.append("```")
                if idx < len(established) - 1:
                    lines.append("")  # blank line between fences -- otherwise
                                       # adjacent ```text blocks can render as
                                       # one merged block
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
    """Human questions/status, not internal counters -- and never a raw
    obligation statement (empirically, real statements are inconsistent
    enough across kinds -- code fragments, boilerplate, genuine prose --
    that showing them verbatim reads as internal, not reviewer-facing; see
    the module-level obligation-filtering notes above). Obligations are
    grouped into a handful of fixed categories instead, one row per
    category, using the worst status in that category. Rows are only added
    when the data supports them -- an empty checklist with just the two
    always-known test lines is a correct, honest render, not a bug."""
    counts = _get(result, "summary", "counts", default={})
    meaningful = _meaningful_obligations(result)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for obligation in meaningful:
        kind = str(_get(obligation, "kind", default=""))
        if kind in _OBLIGATION_CATEGORY_LABEL:
            by_category.setdefault(kind, []).append(obligation)

    lines.append("### Verification")
    lines.append("")
    lines.append("| Area | Status |")
    lines.append("| --- | --- |")
    rows_emitted = 0
    for kind in _OBLIGATION_CATEGORY_ORDER:
        items = by_category.get(kind)
        if not items or rows_emitted >= _MAX_CHECKLIST_ROWS:
            continue
        worst = min(
            items, key=lambda o: _OBLIGATION_STATUS_RANK.get(str(_get(o, "status", default="")), 2)
        )
        status = _OBLIGATION_STATUS_LABEL.get(str(_get(worst, "status", default="")), "Not fully traced")
        lines.append(f"| {_OBLIGATION_CATEGORY_LABEL[kind]} | {status} |")
        rows_emitted += 1

    mapped_tests = counts.get("mapped_tests", 0)
    tests_row = "None identified" if mapped_tests == 0 else str(mapped_tests)
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
    """Only two deterministic, narrowly-scoped rules produce a bullet here --
    both grounded in facts the renderer has already computed elsewhere, so
    nothing is invented that isn't independently shown in System impact or
    Verification:

    1. A boundary was found in `System impact` that reaches beyond the
       traced route(s) (the "Wider API surface" row) -- worth a reviewer's
       explicit attention since it is, by definition, not covered by the
       established path(s) above.
    2. No relevant tests were identified at all for a change with a real,
       found impact -- a safe, generic recommendation that never requires
       guessing what the test should assert.

    Reusing a raw obligation statement here (e.g. "Verify: malformed JSON
    validation") was the exact awkward-bullet problem this rule replaces --
    a fragment with no real sentence around it. When neither rule applies,
    the section is omitted rather than padded with something ungrounded."""
    _rows, wider_areas, has_any_impact = _system_impact_data(result)
    counts = _get(result, "summary", "counts", default={})
    mapped_tests = counts.get("mapped_tests", 0)

    bullets: list[str] = []
    if wider_areas:
        bullets.append("Verify the changed behavior on the wider API surface before merging.")
    if mapped_tests == 0 and has_any_impact:
        bullets.append("Add or run a test covering the affected behavior before merging.")

    if not bullets:
        return

    lines.append("### Before merge")
    lines.append("")
    for bullet in bullets[:_MAX_BEFORE_MERGE]:
        lines.append(f"- {bullet}")
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
        # A coverage-limit note is a global, repository-wide caveat (e.g.
        # "route composition is unresolved ... some routes may be
        # missing"), never a claim about the specific path(s) just shown
        # above -- when one was established, label it as scoped to the
        # REST of the repository so it cannot read as "the path shown here
        # is itself unresolved".
        established_routes, _likely_routes = _flow_routes_by_status(result, _impact_status_by_id(result))
        label = "Other coverage limits" if established_routes else "Coverage limit"
        body.append(f"**{label}:** {coverage_note}")

    # Same "tied to the change, not just present in the repo" bar as the
    # top-level Infrastructure row (see `_infrastructure_row`) -- a
    # repository-wide dependency is not "strong evidence" for this change.
    deps = _as_list(_get(result, "runtime_dependencies", default=[]))
    flow_scoped_deps = [d for d in deps if _get(d, "scope", default="") == "affected_flow"]
    if flow_scoped_deps:
        name = _get(flow_scoped_deps[0], "name", default="")
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
    """One link, not two: until a distinct full-analysis viewer exists
    (there is no dashboard yet), the run URL is the only place to look --
    a second, identically-targeted "View full analysis" link next to
    "View run" would just be the same link twice."""
    lines.append("---")
    footer = "Sydes"
    if run_url:
        footer += f" · [View run]({run_url})"
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
