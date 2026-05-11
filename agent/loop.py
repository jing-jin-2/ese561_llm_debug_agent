"""Main agent loop. Wires the planner, LLM interface, and tools together."""

import json
import os
from typing import Optional

from .llm import (
    LLMClient,
    generate_hypotheses,
    pick_investigation,
    propose_patch,
)
from .planner import plan_next_action, update_score
from .state import AgentState, Hypothesis, HypothesisStatus
from .tools import (
    apply_patch,
    get_traceback_frames,
    read_file,
    revert_patch,
    run_snippet,
    run_tests,
    search_code,
)

DEFAULT_MAX_ITERATIONS = 15


def _signal_changed(old: Optional[dict], new: Optional[dict]) -> bool:
    return json.dumps(old or {}, sort_keys=True) != json.dumps(new or {}, sort_keys=True)


def run_agent(
    target_file: str,
    test_cmd: str,
    llm: Optional[LLMClient] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    verbose: bool = True,
) -> AgentState:
    """Run the debugging agent until the test passes, hypotheses run out, or
    the iteration cap is reached."""

    if llm is None:
        llm = LLMClient()

    state = AgentState(target_file=target_file, test_cmd=test_cmd)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # Initial test run — establishes the failing signal.
    initial_result = run_tests(test_cmd)
    if initial_result["passed"]:
        state.done = True
        state.final_status = "already_passing"
        log("Tests already pass — nothing to do.")
        return state

    state.traceback = initial_result.get("parsed") or {
        "stdout_tail": (initial_result.get("stdout") or "")[-1500:],
        "stderr_tail": (initial_result.get("stderr") or "")[-1500:],
    }
    log(f"Initial failing signal captured.")

    snippet_cwd = os.getcwd()

    while not state.done and state.iteration < max_iterations:
        state.iteration += 1
        log(f"\n=== Iteration {state.iteration} ===")

        action = plan_next_action(state)
        log(f"Planner -> {action['type']}")
        state.log("plan", action=action["type"])

        # ---- Generate hypotheses ----
        if action["type"] == "generate_hypotheses":
            file_content = read_file(target_file)
            try:
                raw_hyps = generate_hypotheses(llm, state, file_content)
            except Exception as e:
                log(f"  hypothesis generation failed: {e}")
                state.log("error", source="generate_hypotheses", content=str(e))
                state.regenerations += 1
                continue

            for h in raw_hyps:
                state.next_hypothesis_id += 1
                hyp = Hypothesis(
                    id=state.next_hypothesis_id,
                    description=h.get("description", ""),
                    suspected_location=h.get("suspected_location"),
                    score=float(h.get("initial_confidence", 0.5)),
                )
                state.hypotheses.append(hyp)
                log(f"  H{hyp.id} (score={hyp.score:.2f}): {hyp.description[:90]}")
            state.regenerations += 1

        # ---- Investigate via a probe ----
        elif action["type"] == "investigate":
            hyp = action["hypothesis"]
            file_content = read_file(target_file)
            try:
                probe = pick_investigation(llm, state, hyp, file_content)
            except Exception as e:
                log(f"  investigation pick failed: {e} — bumping H{hyp.id} so it can be patched next")
                hyp.score += 0.3
                state.log("error", source="pick_investigation", hypothesis=hyp.id, content=str(e))
                continue

            tool = probe["tool"]
            inputs = probe.get("inputs") or {}
            log(f"  Probing H{hyp.id} with {tool} inputs={inputs}")

            if tool == "search_code":
                matches = search_code(inputs.get("pattern", ""), target_file)
                output = "\n".join(f"{ln}: {text}" for ln, text in matches)
                confirmed = len(matches) > 0
                refuted = len(matches) == 0
            elif tool == "run_snippet":
                result = run_snippet(inputs.get("snippet", ""), cwd=snippet_cwd)
                output = (result.get("stdout") or "") + (result.get("stderr") or "")
                expected_true = probe.get("expected_if_true", "")
                expected_false = probe.get("expected_if_false", "")
                confirmed = bool(expected_true) and expected_true in output
                refuted = bool(expected_false) and expected_false in output
            elif tool == "get_traceback_frames":
                tb_text = (state.traceback or {}).get("raw_tail", "") if state.traceback else ""
                frames = get_traceback_frames(tb_text)
                output = "\n".join(f"{f['file']}:{f['line']} {f['function']}" for f in frames)
                confirmed = len(frames) > 0
                refuted = len(frames) == 0
            else:
                output = ""
                confirmed = refuted = False

            log(f"  Probe output: {output.strip()[:200]}")

            if confirmed and not refuted:
                log(f"  -> probe CONFIRMED H{hyp.id}")
                update_score(hyp, "probe_confirmed")
                state.log("probe", hypothesis=hyp.id, tool=tool, result="confirmed", output=output[:500])
            elif refuted and not confirmed:
                log(f"  -> probe REFUTED H{hyp.id}")
                update_score(hyp, "probe_refuted")
                state.log("probe", hypothesis=hyp.id, tool=tool, result="refuted", output=output[:500])
                if hyp.status != HypothesisStatus.OPEN:
                    state.ruled_out.append(hyp.description)
            else:
                log(f"  -> probe inconclusive")
                update_score(hyp, "probe_inconclusive")
                state.log("probe", hypothesis=hyp.id, tool=tool, result="inconclusive", output=output[:500])

        # ---- Propose and verify a patch ----
        elif action["type"] == "propose_patch":
            hyp = action["hypothesis"]
            file_content = read_file(target_file)
            try:
                patch = propose_patch(llm, state, hyp, file_content)
            except Exception as e:
                log(f"  patch proposal failed: {e}")
                update_score(hyp, "patch_proposal_failed")
                state.log("error", source="propose_patch", hypothesis=hyp.id, content=str(e))
                continue

            log(f"  Patching for H{hyp.id}: {patch.get('rationale', '')[:90]}")
            patch_result = apply_patch(target_file, patch.get("old", ""), patch.get("new", ""))
            if not patch_result.get("success"):
                log(f"  patch failed to apply: {patch_result.get('error')}")
                update_score(hyp, "patch_proposal_failed")
                state.log("patch", hypothesis=hyp.id, result="apply_failed", error=patch_result.get("error"))
                continue

            test_result = run_tests(test_cmd)
            new_signal = test_result.get("parsed")

            state.patches_tried.append({
                "hypothesis_id": hyp.id,
                "patch": {"old": patch.get("old"), "new": patch.get("new"),
                          "rationale": patch.get("rationale")},
                "passed": test_result["passed"],
            })

            if test_result["passed"]:
                log(f"  ✓ Tests passed — H{hyp.id} fixed the bug.")
                hyp.status = HypothesisStatus.CONFIRMED
                state.done = True
                state.final_status = "fixed"
                state.log("patch", hypothesis=hyp.id, result="fixed",
                          rationale=patch.get("rationale"))
            else:
                changed = _signal_changed(state.traceback, new_signal)
                log(f"  ✗ Tests still failing (signal_changed={changed}). Reverting.")
                revert_patch(patch_result)
                event = "patch_changed_signal" if changed else "patch_did_nothing"
                update_score(hyp, event)
                state.log("patch", hypothesis=hyp.id, result="reverted",
                          signal_changed=changed)
                if hyp.status != HypothesisStatus.OPEN:
                    state.ruled_out.append(hyp.description)

        # ---- Give up ----
        elif action["type"] == "give_up":
            log(f"  Giving up: {action.get('reason')}")
            state.done = True
            state.final_status = "gave_up"
            state.log("give_up", reason=action.get("reason"))

    if not state.done:
        state.done = True
        state.final_status = "max_iterations_reached"
        log(f"\nStopped: max_iterations ({max_iterations}) reached.")

    return state
