"""Transport for the locked resourcectl v1.1 CLI."""

import asyncio
import json
import math
from contextlib import suppress


class ResourcectlError(Exception):
    """The command failed to provide a valid response."""


def decode(payload):
    try:
        result = json.loads(payload)
    except (UnicodeError, ValueError) as error:
        raise ResourcectlError(f"Invalid resourcectl JSON: {error}") from error
    if not isinstance(result, dict) or result.get("schema_version") != "1.1":
        raise ResourcectlError("Expected a resourcectl v1.1 JSON object")
    return result


def decode_sample(payload):
    sample = decode(payload)
    features = sample.get("workload_features")
    feedback = sample.get("perf_feedback")
    cpu_util = features.get("cpu_util") if isinstance(features, dict) else None
    active = sample.get("active_policy")
    latency_count = feedback.get("sched_lat_samples") if isinstance(feedback, dict) else None
    latency = feedback.get("sched_lat_p99_us") if isinstance(feedback, dict) else None
    if (
        not isinstance(sample.get("sample_id"), str)
        or type(sample.get("ts_ms")) is not int
        or type(sample.get("window_ms")) is not int
        or sample["window_ms"] <= 0
        or "active_policy" not in sample
        or (active is not None and not isinstance(active, str))
        or type(cpu_util) not in (int, float)
        or not 0 <= cpu_util <= 1
        or type(latency_count) is not int
        or latency_count < 0
        or (latency is not None and (
            type(latency) not in (int, float)
            or latency < 0
            or (isinstance(latency, float) and not math.isfinite(latency))
        ))
    ):
        raise ResourcectlError("Invalid v1.1 sample fields used by the Agent")
    return sample


class Resourcectl:
    def __init__(self, command, status_timeout=2.0):
        self.command = command
        self.status_timeout = status_timeout
        self.pending_switch = None

    async def _spawn(self, *args):
        try:
            return await asyncio.create_subprocess_exec(
                *self.command, *args, stdout=asyncio.subprocess.PIPE
            )
        except OSError as error:
            raise ResourcectlError(f"Cannot start resourcectl: {error}") from error

    async def sample(self, interval_ms):
        process = await self._spawn("sample", "--interval-ms", str(interval_ms))
        try:
            async for line in process.stdout:
                yield decode_sample(line)
            if await process.wait() != 0:
                raise ResourcectlError(f"Sampling exited with code {process.returncode}")
        finally:
            if process.returncode is None:
                await self._stop(process)

    @staticmethod
    async def _stop(process):
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.communicate(), timeout=1)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.communicate()

    @staticmethod
    def _response(output, returncode):
        response = decode(output)
        if type(response.get("ok")) is not bool or returncode != (0 if response["ok"] else 1):
            raise ResourcectlError("resourcectl exit code does not match response.ok")
        return response

    async def status(self):
        process = await self._spawn("sched", "status")
        try:
            output, _ = await asyncio.wait_for(process.communicate(), self.status_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self._stop(process)
            raise
        return self._response(output, process.returncode)

    async def _switch(self, request_id, target):
        process = await self._spawn("sched", "switch", "--request-id", request_id, "--target", target)
        output, _ = await process.communicate()
        result = self._response(output, process.returncode)
        if result.get("request_id") != request_id:
            raise ResourcectlError("Unexpected switch response request_id")
        return result

    async def switch(self, request_id, target, timeout):
        if self.pending_switch is not None and not self.pending_switch.done():
            raise ResourcectlError("A local switch process is still running")
        self.pending_switch = asyncio.create_task(self._switch(request_id, target))
        self.pending_switch.add_done_callback(self._consume_result)
        return await asyncio.wait_for(asyncio.shield(self.pending_switch), timeout)

    @staticmethod
    def _consume_result(task):
        if not task.cancelled():
            task.exception()

    async def finish(self, timeout):
        if self.pending_switch is not None:
            with suppress(ResourcectlError):
                await asyncio.wait_for(asyncio.shield(self.pending_switch), timeout)
