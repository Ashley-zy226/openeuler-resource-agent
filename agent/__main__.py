"""Run the scheduling Agent with a Mock or an openEuler resourcectl executable."""

import argparse
import asyncio
import json
import math
import sys
from contextlib import aclosing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .registry import Registry
from .resourcectl import Resourcectl, ResourcectlError
from .scheduling import SchedulingSkill

DEFAULT_REPLAY = Path(__file__).resolve().parents[1] / "fixtures" / "agent" / "synthetic.jsonl"


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, allow_nan=False), flush=True)


async def wait_for_result(status_tool, request_id, budget, context):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while loop.time() < deadline:
        try:
            status = await asyncio.wait_for(status_tool(), deadline - loop.time())
        except (ResourcectlError, asyncio.TimeoutError) as error:
            log("status_unavailable", **context, error=str(error))
            return None

        log("status_checked", **context, status=status)
        if not status["ok"] or "in_flight_request_id" not in status:
            return None
        if status["in_flight_request_id"] is None:
            result = status.get("last_switch_result")
            if isinstance(result, dict) and result.get("request_id") == request_id:
                return result
            return None
        await asyncio.sleep(min(0.05, max(0, deadline - loop.time())))
    return None


async def execute_switch(tools, sample, decision, args):
    context = {"sample_id": sample["sample_id"], "target": decision.target}
    try:
        status = await tools["sched.status"]()
    except (ResourcectlError, asyncio.TimeoutError) as error:
        log("switch_skipped", **context, reason="status_unavailable", error=str(error))
        return
    if (
        not status["ok"]
        or "in_flight_request_id" not in status
        or status["in_flight_request_id"] is not None
        or status.get("active_policy") != sample["active_policy"]
    ):
        log("switch_skipped", **context, reason="state_unconfirmed_or_changed", status=status)
        return

    request_id = uuid4().hex
    context["request_id"] = request_id
    log("switch_requested", **context, reason=decision.reason)
    try:
        result = await tools["sched.switch"](request_id, decision.target, args.switch_timeout)
    except asyncio.TimeoutError:
        log("switch_timeout", **context)
        result = await wait_for_result(tools["sched.status"], request_id, args.status_wait, context)
    except ResourcectlError as error:
        log("switch_result_unknown", **context, error=str(error))
        return

    if result is None:
        log("switch_result_unknown", **context)
    else:
        log("switch_result", **context, result=result)


async def run(command, args, dry_run):
    backend = Resourcectl(command)
    tools = Registry()
    tools.register("sample", backend.sample)
    tools.register("sched.status", backend.status)
    tools.register("sched.switch", backend.switch)

    skills = Registry()
    skills.register(
        "scheduling",
        SchedulingSkill(args.cpu_high, args.cpu_low, args.confirm_windows, args.min_residency_ms, args.busy_policy),
    )
    scheduling = skills["scheduling"]
    try:
        async with aclosing(tools["sample"](args.interval_ms)) as stream:
            async for sample in stream:
                decision = scheduling(sample)
                feedback = sample["perf_feedback"]
                p99 = feedback["sched_lat_p99_us"] if feedback["sched_lat_samples"] >= 50 else None
                log(
                    "decision",
                    sample_id=sample["sample_id"],
                    ts_ms=sample["ts_ms"],
                    active_policy=sample["active_policy"],
                    cpu_util=sample["workload_features"]["cpu_util"],
                    usable_sched_lat_p99_us=p99,
                    sched_lat_samples=feedback["sched_lat_samples"],
                    dry_run=dry_run,
                    **asdict(decision),
                )
                if decision.target is not None and not dry_run:
                    await execute_switch(tools, sample, decision, args)
                    scheduling.reset_confirmation()
    finally:
        try:
            await backend.finish(args.status_wait)
        except asyncio.TimeoutError:
            print("A switch process still has no confirmed completion", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resourcectl", help="Path to the real resourcectl executable (dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Log decisions without sending switches")
    parser.add_argument("--samples", type=Path, default=DEFAULT_REPLAY, help="Mock input JSONL")
    parser.add_argument("--scenario", choices=("success", "timeout_then_load_failed"), default="success")
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--cpu-high", type=float, default=0.70)
    parser.add_argument("--cpu-low", type=float, default=0.30)
    parser.add_argument("--busy-policy", default="scx_rusty")
    parser.add_argument("--confirm-windows", type=int, default=2)
    parser.add_argument("--min-residency-ms", type=int, default=2000)
    parser.add_argument("--switch-timeout", type=float, default=0.25)
    parser.add_argument("--status-wait", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 <= args.cpu_low < args.cpu_high <= 1:
        parser.error("require 0 <= cpu-low < cpu-high <= 1")
    if args.confirm_windows <= 0 or args.interval_ms <= 0 or args.min_residency_ms < 0:
        parser.error("interval and confirmation windows must be positive, and residency nonnegative")
    if any(not math.isfinite(limit) or limit <= 0 for limit in (args.switch_timeout, args.status_wait)):
        parser.error("timeouts must be finite and positive")
    try:
        if args.resourcectl:
            asyncio.run(run([args.resourcectl], args, dry_run=True))
        else:
            with TemporaryDirectory(prefix="agent-mock-") as directory:
                command = [
                    sys.executable, "-m", "agent.mock_resourcectl",
                    "--state", str(Path(directory) / "state.json"),
                    "--samples", str(args.samples),
                    "--scenario", args.scenario,
                ]
                asyncio.run(run(command, args, dry_run=args.dry_run))
    except ResourcectlError as error:
        print(error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
