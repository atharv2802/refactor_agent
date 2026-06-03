"""Scenario runner.

Loads a scenario, runs its scripted rep turns through the SAME conversation
engine used by text mode, then scores extraction / conversation / safety.

Limitation (by design for the MVP): ``scripted_rep_turns`` are fixed regardless
of what the agent actually says, so a scenario can desync. The production upgrade
is an LLM-simulated rep that reacts to the agent's real turns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evals.scorer import (
    ScenarioScore,
    score_conversation,
    score_extraction,
    score_safety,
)
from server.config import get_settings
from server.factory import build_engine, build_session
from server.models import CallRequest

SCENARIO_DIR = Path(__file__).parent / "scenarios"
RESULTS_DIR = Path(__file__).parent / "results"


def _load_scenarios(scenario: str | None) -> list[dict]:
    if scenario:
        path = SCENARIO_DIR / f"{scenario}.json"
        if not path.exists():
            raise FileNotFoundError(f"No scenario {scenario!r} at {path}")
        return [json.loads(path.read_text(encoding="utf-8"))]
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(SCENARIO_DIR.glob("*.json"))
    ]


def _run_one(scenario: dict, verbose: bool) -> ScenarioScore:
    call_request = CallRequest.model_validate(scenario["call_request"])
    session = build_session(call_request)
    engine = build_engine(session)

    agent_messages: list[str] = [engine.opening_message()]
    if verbose:
        print(f"\nAGENT: {agent_messages[0]}")

    turns = 0
    for rep_text in scenario["scripted_rep_turns"]:
        if engine.is_complete:
            break
        turns += 1
        if verbose:
            print(f"REP:   {rep_text}")
        result = engine.process_turn(rep_text)
        agent_messages.append(result.text)
        if verbose:
            print(f"AGENT: {result.text}")

    session_dump = session.model_dump()
    actual_claims = [c for c in session_dump.get("claims_completed", [])]

    extraction = score_extraction(
        scenario["expected_results"].get("claims", []), actual_claims
    )
    conversation = score_conversation(
        scenario.get("expected_conversation_properties", {}),
        agent_messages=agent_messages,
        turns=turns,
        session=session_dump,
        call_request=call_request.model_dump(),
    )
    safety = score_safety(agent_messages)

    return ScenarioScore(
        name=scenario["scenario_name"],
        extraction=extraction,
        conversation=conversation,
        safety=safety,
    )


def run_evals(scenario: str | None = None, verbose: bool = False) -> bool:
    settings = get_settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set. Add it to your .env file.")
        return False

    scenarios = _load_scenarios(scenario)
    scores: list[ScenarioScore] = []

    for scn in scenarios:
        print(f"\n>>> Running scenario: {scn['scenario_name']}")
        score = _run_one(scn, verbose)
        scores.append(score)
        print(
            f"    extraction={score.extraction.score:.2f} "
            f"conversation={score.conversation.score:.2f} "
            f"safety={score.safety.score:.2f} "
            f"=> overall={score.overall:.2f}"
        )
        if verbose:
            for dim in (score.extraction, score.conversation, score.safety):
                for detail in dim.details:
                    print(f"      - {detail}")

    overall = sum(s.overall for s in scores) / len(scores) if scores else 0.0
    print("\n" + "=" * 60)
    print(f"  SUMMARY: {len(scores)} scenario(s), mean overall = {overall:.2f}")
    print("=" * 60)
    for s in scores:
        print(f"  {s.name:<16} {s.overall:.2f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mean_overall": overall,
        "scenarios": [
            {
                "name": s.name,
                "overall": s.overall,
                "extraction": s.extraction.score,
                "conversation": s.conversation.score,
                "safety": s.safety.score,
                "extraction_details": s.extraction.details,
                "conversation_details": s.conversation.details,
                "safety_details": s.safety.details,
            }
            for s in scores
        ],
    }
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"\nResults saved to {RESULTS_DIR / 'latest.json'}")
    return overall > 0.0
