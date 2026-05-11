"""CLI entry point for the debugging agent."""

import argparse
import json
import sys

from agent.llm import DEFAULT_OLLAMA_MODEL, LLMClient
from agent.loop import DEFAULT_MAX_ITERATIONS, run_agent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hypothesis-driven LLM debugging agent",
    )
    parser.add_argument("--file", required=True, help="Target Python file containing the bug")
    parser.add_argument("--test", required=True, help="Test command, e.g. 'pytest examples/test_buggy_sum.py'")
    parser.add_argument("--max-iter", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--trace-out", help="Optional path to write the full trace as JSON")
    args = parser.parse_args()

    llm = LLMClient(model=args.model)
    state = run_agent(
        target_file=args.file,
        test_cmd=args.test,
        llm=llm,
        max_iterations=args.max_iter,
        verbose=not args.quiet,
    )

    print()
    print("=" * 60)
    print(f"Final status     : {state.final_status}")
    print(f"Iterations used  : {state.iteration}")
    print(f"Patches tried    : {len(state.patches_tried)}")
    print(f"Hypotheses total : {len(state.hypotheses)}")
    print(f"LLM calls        : {llm.call_count}")
    print("=" * 60)

    if args.trace_out:
        with open(args.trace_out, "w") as f:
            json.dump({
                "final_status": state.final_status,
                "iterations": state.iteration,
                "llm_calls": llm.call_count,
                "hypotheses": [
                    {
                        "id": h.id,
                        "description": h.description,
                        "suspected_location": h.suspected_location,
                        "score": h.score,
                        "status": h.status.value,
                    }
                    for h in state.hypotheses
                ],
                "patches_tried": state.patches_tried,
                "history": state.history,
            }, f, indent=2)
        print(f"Trace written to {args.trace_out}")

    return 0 if state.final_status == "fixed" else 1


if __name__ == "__main__":
    sys.exit(main())
