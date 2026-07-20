"""Shared pipeline metrics reported through the heartbeat.

The device measures; the backend judges. These accumulators hold raw stage
timings and event counts so each heartbeat can carry a since-last-heartbeat
window (plus cumulative totals) for backend-side threshold alerting -- no
alert policy lives on the device.

Backed by multiprocessing primitives so the detection subprocess (spawned
with the "spawn" context) records into the same counters the parent process
snapshots. The objects are cheap and work identically when everything runs
in one process.
"""
from __future__ import annotations

import multiprocessing
from typing import Any, Optional


class StageTimings:
    """Duration accumulator for one pipeline stage (e.g. detection).

    ``record`` adds one sample; ``snapshot`` reports the window since the
    previous snapshot -- count/avg/max -- plus cumulative totals, and resets
    the window (the heartbeat is the sole windowed consumer)."""

    def __init__(self, ctx: Any = None) -> None:
        mp = ctx or multiprocessing
        self._lock = mp.Lock()
        self._count = mp.Value("Q", 0, lock=False)
        self._sum = mp.Value("d", 0.0, lock=False)
        self._max = mp.Value("d", 0.0, lock=False)
        self._total_count = mp.Value("Q", 0, lock=False)
        self._total_seconds = mp.Value("d", 0.0, lock=False)

    def record(self, seconds: float) -> None:
        with self._lock:
            self._count.value += 1
            self._sum.value += seconds
            if seconds > self._max.value:
                self._max.value = seconds
            self._total_count.value += 1
            self._total_seconds.value += seconds

    def snapshot(self, reset: bool = True) -> dict:
        with self._lock:
            count = self._count.value
            window_sum = self._sum.value
            window_max = self._max.value
            result = {
                "count": count,
                "avg_seconds": round(window_sum / count, 3) if count else None,
                "max_seconds": round(window_max, 3) if count else None,
                "total_count": self._total_count.value,
                "total_seconds": round(self._total_seconds.value, 3),
            }
            if reset:
                self._count.value = 0
                self._sum.value = 0.0
                self._max.value = 0.0
        return result


class EventCounter:
    """Monotonic cross-process event count (e.g. unhealthy results)."""

    def __init__(self, ctx: Any = None) -> None:
        mp = ctx or multiprocessing
        self._value = mp.Value("Q", 0)

    def increment(self) -> None:
        with self._value.get_lock():
            self._value.value += 1

    @property
    def value(self) -> int:
        return self._value.value


class PipelineMetrics:
    """The metrics bundle one Pipeline (parent + optional detection child) shares."""

    def __init__(self, ctx: Optional[Any] = None) -> None:
        self.detection = StageTimings(ctx)
        self.classification = StageTimings(ctx)
        self.unhealthy_results = EventCounter(ctx)
