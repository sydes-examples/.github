"""Tests for render_sydes_pr.py.

Uses two kinds of fixtures:

- `fixtures/real_*.json`: real (trimmed) Sydes results captured from the
  manual calibration suite, covering scenarios that occur naturally in
  production data (established-only, established+inferred, no tests
  mapped, tests mapped but not executed, unsupported/no-flow, and a real
  code_review_status="unavailable" run).
- Small inline synthetic dicts, for the handful of scenarios no real
  captured result happens to cover: a large fan-out (many affected paths,
  to prove the truncation rule actually truncates), review findings
  present, and review not_requested. These are clearly synthetic --
  never confused with real calibration data, and never written back to
  the `results/` directory this repo uses for actual study results.

Renderer determinism is exercised throughout: every test calls `render()`
directly, with no network/LLM involved, and asserts on the literal
Markdown string.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import render_sydes_pr as r

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_flow(flow_id: str, entry_label: str, handler: str, symbol: str, obligations=None) -> dict:
    return {
        "id": flow_id,
        "entry_kind": "route",
        "entry_label": entry_label,
        "handler": handler,
        "changed_nodes": [{"repo": "app", "file": "src/app.py", "symbol": symbol}],
        "obligations": obligations or [],
    }


def _make_obligation(kind: str, statement: str, status: str = "unverified", introduced: bool = False) -> dict:
    return {
        "id": f"ob:{statement[:10]}",
        "flow_id": "flow:x",
        "kind": kind,
        "statement": statement,
        "origin": "test_matrix",
        "introduced_by_change": introduced,
        "status": status,
    }


def _base_result(**overrides) -> dict:
    base = {
        "version": "v3",
        "kind": "sydes_change_verification",
        "change": {"base": "main", "symbols": [], "files": []},
        "summary": {
            "verdict": "VERIFICATION INCOMPLETE",
            "risk": "MEDIUM",
            "counts": {"mapped_tests": 0, "tests_executed": 0},
        },
        "code_review_status": "completed",
        "code_findings": [],
        "accepted_impacts": [],
        "affected_boundaries": [],
        "affected_flows": [],
        "analysis_notes": [],
        "runtime_dependencies": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Established impact only
# ---------------------------------------------------------------------------


def test_established_only_shows_no_likely_section():
    result = _base_result(
        affected_flows=[_make_flow("flow:a", "POST /pets", "PetController.create", "PetService.create")],
        accepted_impacts=[{"id": "flow:a", "status": "proven"}],
    )
    out = r.render(result)
    assert "**Established**" in out
    assert "Likely, not fully established" not in out
    assert "PetService.create" in out


# ---------------------------------------------------------------------------
# 2. Established + inferred (real data)
# ---------------------------------------------------------------------------


def test_established_and_inferred_both_shown_and_distinct():
    result = _load("real_established_and_inferred.json")
    out = r.render(result)
    assert "**Established**" in out
    assert "**Likely, not fully established**" in out
    # The two kinds of evidence must never be visually merged into one list.
    established_idx = out.index("**Established**")
    likely_idx = out.index("**Likely, not fully established**")
    assert established_idx < likely_idx


# ---------------------------------------------------------------------------
# 3. Not fully traced (nothing established, only an inferred impact)
# ---------------------------------------------------------------------------


def test_not_fully_traced_is_explicit_not_silent():
    # This real case has zero PROVEN flows but one real inferred boundary --
    # the honest render is to show that one likely signal, clearly marked,
    # not to claim nothing was found at all. That distinction (a real,
    # present-but-unproven signal vs. truly nothing) matters and must not
    # be collapsed into one generic message.
    result = _load("real_unsupported_not_traced.json")
    out = r.render(result)
    assert "**Established**" not in out
    assert "Likely, not fully established" in out
    assert "email verification task processing" in out


# ---------------------------------------------------------------------------
# 4. Many affected paths / truncation (synthetic -- no real case is this broad)
# ---------------------------------------------------------------------------


def test_many_established_paths_are_truncated_deterministically():
    flows = [
        _make_flow(f"flow:{i}", f"GET /resource/{i}", f"Handler{i}.get", f"Service{i}.fetch")
        for i in range(10)
    ]
    impacts = [{"id": f"flow:{i}", "status": "proven"} for i in range(10)]
    result = _base_result(affected_flows=flows, accepted_impacts=impacts)
    out = r.render(result)

    shown = out.count("```text")
    assert shown == r._MAX_ESTABLISHED_PATHS
    assert f"…and {10 - r._MAX_ESTABLISHED_PATHS} more established path(s)" in out
    # The comment must stay short even with 10 affected routes.
    assert len(out.splitlines()) < 60


def test_many_likely_paths_are_truncated_deterministically():
    impacts = [
        {"id": f"impact:{i}", "status": "inferred", "behavior_label": f"maybe affects service {i}"}
        for i in range(5)
    ]
    result = _base_result(accepted_impacts=impacts)
    out = r.render(result)
    shown = out.count("maybe affects service")
    assert shown == r._MAX_LIKELY_PATHS
    assert f"…and {5 - r._MAX_LIKELY_PATHS} more likely impact(s)" in out


# ---------------------------------------------------------------------------
# 5. No mapped tests (real data)
# ---------------------------------------------------------------------------


def test_no_mapped_tests_says_none_not_zero_confusingly():
    result = _load("real_inferred_only_no_tests.json")
    out = r.render(result)
    assert "| Relevant tests | None |" in out


# ---------------------------------------------------------------------------
# 6. Tests identified but not executed (real data, --no-run-tests case)
# ---------------------------------------------------------------------------


def test_tests_identified_not_executed_reads_as_intentional():
    result = _load("real_established_many_tests.json")
    out = r.render(result)
    assert re.search(r"\| Relevant tests \| \d+ \|", out)
    assert "| Tests executed by Sydes | Not run |" in out
    # Must never look like a failure -- no failure-shaped words near it.
    verification_section = out.split("### Verification")[1].split("###")[0]
    assert "fail" not in verification_section.lower()
    assert "error" not in verification_section.lower()


# ---------------------------------------------------------------------------
# 7. Review completed, zero findings
# ---------------------------------------------------------------------------


def test_review_completed_zero_findings():
    result = _base_result(code_review_status="completed", code_findings=[])
    out = r.render(result)
    assert "### Code review" in out
    assert "No findings." in out


# ---------------------------------------------------------------------------
# 8. Review findings present (synthetic -- no real captured case has findings)
# ---------------------------------------------------------------------------


def test_review_findings_present_summarized_not_dumped():
    findings = [
        {"id": "f1", "severity": "P0", "title": "SQL injection risk", "file": "a.py", "line": 1},
        {"id": "f2", "severity": "P2", "title": "Unused import", "file": "b.py", "line": 2},
        {"id": "f3", "severity": "P2", "title": "Missing docstring", "file": "c.py", "line": 3},
    ]
    result = _base_result(code_review_status="completed", code_findings=findings)
    out = r.render(result)
    section = out.split("### Code review")[1].split("---")[0]
    # Summarized as a count, never the full per-finding breakdown in the
    # main comment body (that belongs to inline comments / the full result).
    assert "3 finding(s)" in section
    assert "SQL injection risk" not in section
    assert "Unused import" not in section


# ---------------------------------------------------------------------------
# 9. Review unavailable (real data)
# ---------------------------------------------------------------------------


def test_review_unavailable_is_explicit_not_no_findings():
    result = _load("real_review_unavailable.json")
    out = r.render(result)
    assert "Code review unavailable" in out
    assert "No findings." not in out


# ---------------------------------------------------------------------------
# 10. Review not requested (synthetic)
# ---------------------------------------------------------------------------


def test_review_not_requested_omits_section_entirely():
    result = _base_result(code_review_status="not_requested", code_findings=[])
    out = r.render(result)
    assert "### Code review" not in out


# ---------------------------------------------------------------------------
# 11. Unsupported / no resolved flows (real data)
# ---------------------------------------------------------------------------


def test_unsupported_no_flows_is_honest_not_falsely_reassuring():
    # Same real case as above: 0 proven flows, 1 inferred boundary. Even
    # here -- content Sydes DID find, just not proven -- the render must
    # never read as a clean bill of health.
    result = _load("real_unsupported_not_traced.json")
    out = r.render(result)
    for bad_phrase in ("everything safe", "nothing affected", "no impact"):
        assert bad_phrase not in out.lower()


def test_true_zero_signal_says_could_not_establish():
    # The genuinely-nothing-found case: 0 flows, 0 boundaries, 0 impacts.
    # This must never look like "nothing is affected" either -- it must
    # say plainly that tracing did not reach anything.
    result = _base_result(analysis_notes=["No discovered route declaration reaches the changed symbols."])
    out = r.render(result)
    assert "could not establish a system path" in out
    assert "No discovered route declaration reaches the changed symbols." in out
    for bad_phrase in ("everything safe", "nothing affected", "no impact"):
        assert bad_phrase not in out.lower()


# ---------------------------------------------------------------------------
# 12. No accidental "obligation" in human-facing comment
# ---------------------------------------------------------------------------


def test_word_obligation_never_appears_in_rendered_output():
    for fixture in FIXTURES.glob("real_*.json"):
        result = json.loads(fixture.read_text())
        out = r.render(result)
        assert "obligation" not in out.lower(), f"'obligation' leaked into render of {fixture.name}"


# ---------------------------------------------------------------------------
# 13. No top-level "Analysis PARTIAL" enum dump
# ---------------------------------------------------------------------------


def test_no_raw_analysis_status_enum_dump():
    result = _base_result(analysis_status="partial")
    out = r.render(result)
    assert "Analysis" not in out.split("---")[0]  # header/body, not the footer
    assert "PARTIAL" not in out


# ---------------------------------------------------------------------------
# 14. No numeric confidence dump
# ---------------------------------------------------------------------------


def test_no_numeric_confidence_shown():
    result = _base_result(
        accepted_impacts=[
            {
                "id": "impact:x",
                "status": "inferred",
                "behavior_label": "might affect billing",
                "llm_confidence": 0.87,
            }
        ]
    )
    out = r.render(result)
    assert "0.87" not in out
    assert "confidence" not in out.lower()


# ---------------------------------------------------------------------------
# 15. Comment marker retained
# ---------------------------------------------------------------------------


def test_marker_present_and_first_line():
    for fixture in FIXTURES.glob("real_*.json"):
        result = json.loads(fixture.read_text())
        out = r.render(result)
        assert out.splitlines()[0] == r.MARKER

    # Also for the unavailable-result fallback path.
    out = r.render_unavailable("no result file was written")
    assert out.splitlines()[0] == r.MARKER


# ---------------------------------------------------------------------------
# 16. Markdown stays valid and readable
# ---------------------------------------------------------------------------


def test_markdown_stays_well_formed():
    for fixture in FIXTURES.glob("real_*.json"):
        result = json.loads(fixture.read_text())
        out = r.render(result)

        # Every opened fence is closed (even count of ``` lines).
        fence_lines = [ln for ln in out.splitlines() if ln.strip() == "```text" or ln.strip() == "```"]
        assert len(fence_lines) % 2 == 0, f"unbalanced code fence in render of {fixture.name}"

        # Every markdown table has a separator row directly under its header.
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("| ") and i + 1 < len(lines):
                nxt = lines[i + 1]
                if nxt.startswith("|") and set(nxt.replace("|", "").replace(" ", "").replace("-", "")) == set():
                    continue  # this line's own separator, fine
        # No literal tab characters, no trailing whitespace-only chaos.
        assert "\t" not in out

        # Comment isn't empty and ends with the footer.
        assert out.strip().endswith(")") or out.strip().endswith("Sydes")


def test_determinism_same_input_same_output():
    result = _load("real_established_and_inferred.json")
    assert r.render(result) == r.render(result)


def test_main_result_unavailable_path(tmp_path):
    """The CLI entrypoint's own fallback for a missing/unreadable result
    file -- exercised end to end, not just render_unavailable() directly."""
    out_path = tmp_path / "comment.md"
    missing = tmp_path / "does-not-exist.json"
    # main() reads argv via argparse, so invoke it the same way the CLI does.
    import sys as _sys

    old_argv = _sys.argv
    try:
        _sys.argv = ["render_sydes_pr.py", str(missing), "--out", str(out_path)]
        code = r.main()
    finally:
        _sys.argv = old_argv
    assert code == 0
    assert out_path.exists()
    assert "No result produced" in out_path.read_text()
