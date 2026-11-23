"""A configurable, replayable baseline scheduling Skill."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    workload: str
    target: str | None
    reason: str
    confirmed_windows: int


class SchedulingSkill:
    def __init__(self, cpu_high, cpu_low, confirm_windows, min_residency_ms, busy_policy):
        self.cpu_high = cpu_high
        self.cpu_low = cpu_low
        self.confirm_windows = confirm_windows
        self.min_residency_ms = min_residency_ms
        self.policy_by_workload = {"idle": "default", "cpu_busy": busy_policy}
        self._candidate = None
        self._windows = 0
        self._active_policy = None
        self._policy_since_ms = None

    def reset_confirmation(self):
        self._candidate = None
        self._windows = 0

    def __call__(self, sample):
        cpu_util = sample["workload_features"]["cpu_util"]
        if cpu_util >= self.cpu_high:
            workload = "cpu_busy"
        elif cpu_util <= self.cpu_low:
            workload = "idle"
        else:
            workload = "uncertain"

        active = sample["active_policy"]
        timestamp = sample["ts_ms"]
        if active != self._active_policy:
            self.reset_confirmation()
            self._active_policy = active
            self._policy_since_ms = timestamp

        candidate = self.policy_by_workload.get(workload)
        if active is None or candidate is None or candidate == active:
            self.reset_confirmation()
            reason = "policy_unknown" if active is None else "workload_uncertain"
            if active is not None and candidate == active:
                reason = "policy_already_matches"
            return Decision(workload, None, reason, 0)

        if candidate != self._candidate:
            self._candidate = candidate
            self._windows = 0
        self._windows += 1

        if self._windows < self.confirm_windows:
            return Decision(workload, None, "awaiting_confirmation", self._windows)
        if timestamp - self._policy_since_ms < self.min_residency_ms:
            return Decision(workload, None, "minimum_residency", self._windows)
        return Decision(workload, candidate, "confirmed_policy_change", self._windows)
