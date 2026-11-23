"""Stateful resourcectl CLI for macOS/Linux development without a scheduler."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "resourcectl-v1.1"


def read_status(state, responses):
    if state.exists():
        return json.loads(state.read_text())
    return responses["status"]["default"].copy()


def write_status(state, status):
    temporary = state.with_name(f"{state.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(status))
    temporary.replace(state)


def emit(document):
    print(json.dumps(document, allow_nan=False), flush=True)


def sample(args, responses):
    with args.samples.open() as source:
        for index, line in enumerate(source):
            if index:
                time.sleep(args.interval_ms / 1000)
            snapshot = json.loads(line)
            if snapshot["active_policy"] is not None:
                snapshot["active_policy"] = read_status(args.state, responses)["active_policy"]
            emit(snapshot)
    return 0


def switch(args, responses):
    current = read_status(args.state, responses)
    previous = current["active_policy"]
    if args.target not in {"default", "scx_rusty"}:
        case = "invalid_target"
    elif args.target == previous:
        case = "already_active"
    elif args.scenario == "timeout_then_load_failed":
        case = "load_failed_restored_default"
        write_status(args.state, dict(current, in_flight_request_id=args.request_id))
        time.sleep(args.switch_delay)
    else:
        case = "success"

    result = dict(responses["switch"][case], request_id=args.request_id, previous_policy=previous)
    if result["ok"]:
        result["active_policy"] = args.target
    elif case == "invalid_target":
        result["active_policy"] = previous

    if case != "invalid_target":
        status_key = "default" if result["active_policy"] == "default" else "agent_managed_scx_rusty"
        new_status = dict(responses["status"][status_key], last_switch_result=result)
        write_status(args.state, new_status)
    emit(result)
    return 0 if result["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--scenario", choices=("success", "timeout_then_load_failed"), default="success")
    parser.add_argument("--switch-delay", type=float, default=0.65)
    commands = parser.add_subparsers(dest="command", required=True)
    sampler = commands.add_parser("sample")
    sampler.add_argument("--interval-ms", type=int, default=1000)
    sched = commands.add_parser("sched")
    actions = sched.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    switching = actions.add_parser("switch")
    switching.add_argument("--request-id", required=True)
    switching.add_argument("--target", required=True)
    args = parser.parse_args()
    responses = json.loads((FIXTURES / "responses.json").read_text())
    if args.command == "sample":
        return sample(args, responses)
    if args.action == "status":
        emit(read_status(args.state, responses))
        return 0
    return switch(args, responses)


if __name__ == "__main__":
    raise SystemExit(main())
