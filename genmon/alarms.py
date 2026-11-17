"""Threshold alarms with hysteresis and an on-delay.

Each monitored channel has up to four limits (warning/critical, high/low).

* **Hysteresis** - once a limit is active, the value must move back past
  ``limit -/+ hysteresis`` before the alarm clears. This stops an alarm from
  chattering when a noisy value sits right on a threshold.
* **On-delay** - an escalation (NORMAL->WARNING, WARNING->CRITICAL) is only
  latched after the condition has persisted for ``delay`` seconds. Short
  transients such as the frequency dip on a load step are ignored.
  De-escalation is immediate once the value has cleared the hysteresis band.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Mapping

_EPS = 1e-9


class Level(IntEnum):
    NORMAL = 0
    WARNING = 1
    CRITICAL = 2


@dataclass(frozen=True)
class Thresholds:
    warn_high: float | None = None
    crit_high: float | None = None
    warn_low: float | None = None
    crit_low: float | None = None
    hysteresis: float = 0.0
    delay: float = 0.0

    def __post_init__(self) -> None:
        if self.hysteresis < 0 or self.delay < 0:
            raise ValueError("hysteresis and delay must be non-negative")
        if (self.warn_high is not None and self.crit_high is not None
                and self.crit_high < self.warn_high):
            raise ValueError("crit_high must be >= warn_high")
        if (self.warn_low is not None and self.crit_low is not None
                and self.crit_low > self.warn_low):
            raise ValueError("crit_low must be <= warn_low")


@dataclass(frozen=True)
class AlarmEvent:
    t: float
    channel: str
    previous: Level
    level: Level
    value: float

    def __str__(self) -> str:
        kind = "CLEARED" if self.level < self.previous else "RAISED"
        return (f"t={self.t:8.1f}s  {self.channel:<12} {kind:<8} "
                f"{self.previous.name} -> {self.level.name}  (value={self.value:.2f})")


class ChannelMonitor:
    def __init__(self, channel: str, thresholds: Thresholds) -> None:
        self.channel = channel
        self.th = thresholds
        self.level = Level.NORMAL
        self._pending_since: float | None = None

    def _over_high(self, value: float, limit: float | None, lvl: Level) -> bool:
        if limit is None:
            return False
        relax = self.th.hysteresis if self.level >= lvl else 0.0
        return value >= limit - relax

    def _under_low(self, value: float, limit: float | None, lvl: Level) -> bool:
        if limit is None:
            return False
        relax = self.th.hysteresis if self.level >= lvl else 0.0
        return value <= limit + relax

    def classify(self, value: float) -> Level:
        """Instantaneous level for ``value``, taking hysteresis into account."""
        th = self.th
        if (self._over_high(value, th.crit_high, Level.CRITICAL)
                or self._under_low(value, th.crit_low, Level.CRITICAL)):
            return Level.CRITICAL
        if (self._over_high(value, th.warn_high, Level.WARNING)
                or self._under_low(value, th.warn_low, Level.WARNING)):
            return Level.WARNING
        return Level.NORMAL

    def update(self, t: float, value: float) -> AlarmEvent | None:
        raw = self.classify(value)

        if raw <= self.level:
            self._pending_since = None
            return self._transition(t, raw, value) if raw < self.level else None

        if self._pending_since is None:
            self._pending_since = t
        if t - self._pending_since >= self.th.delay - _EPS:
            self._pending_since = None
            return self._transition(t, raw, value)
        return None

    def _transition(self, t: float, new: Level, value: float) -> AlarmEvent:
        event = AlarmEvent(t, self.channel, self.level, new, value)
        self.level = new
        return event


@dataclass
class AlarmManager:
    monitors: dict[str, ChannelMonitor] = field(default_factory=dict)
    log: list[AlarmEvent] = field(default_factory=list)

    @classmethod
    def from_thresholds(cls, thresholds: Mapping[str, Thresholds]) -> "AlarmManager":
        return cls({name: ChannelMonitor(name, th) for name, th in thresholds.items()})

    def update(self, t: float, values: Mapping[str, float]) -> list[AlarmEvent]:
        events = []
        for name, monitor in self.monitors.items():
            event = monitor.update(t, values[name])
            if event is not None:
                events.append(event)
        self.log.extend(events)
        return events

    @property
    def overall(self) -> Level:
        return max((m.level for m in self.monitors.values()), default=Level.NORMAL)

    def levels(self) -> dict[str, Level]:
        return {name: m.level for name, m in self.monitors.items()}


def peak_levels(events: Iterable[AlarmEvent]) -> dict[str, Level]:
    """Highest level each channel reached over a run."""
    peaks: dict[str, Level] = {}
    for e in events:
        peaks[e.channel] = max(peaks.get(e.channel, Level.NORMAL), e.level)
    return peaks
