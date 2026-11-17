"""Scenarios, configuration loading and the simulation loop."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, fields
from pathlib import Path

from .alarms import AlarmEvent, AlarmManager, Thresholds
from .model import Generator, GeneratorParams, Sample

CHANNELS = ("voltage", "current", "frequency", "temperature")


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    duration: float
    load_steps: tuple[tuple[float, float], ...]   # (time s, load kW)


# Rated output of the default genset is 500 kVA * 0.8 pf = 400 kW.
SCENARIOS: dict[str, Scenario] = {
    "normal": Scenario(
        "normal", "Routine load changes within rating (expect no alarms)",
        duration=240.0,
        load_steps=((1.0, 100.0), (30.0, 200.0), (60.0, 300.0),
                    (120.0, 200.0), (180.0, 250.0)),
    ),
    "overload": Scenario(
        "overload", "Sustained 120% load, then load shed back to 50%",
        duration=600.0,
        load_steps=((1.0, 100.0), (10.0, 200.0), (20.0, 300.0),
                    (30.0, 480.0), (400.0, 200.0)),
    ),
    "load_rejection": Scenario(
        "load_rejection", "Breaker trip drops 95% load at once",
        duration=120.0,
        load_steps=((1.0, 100.0), (10.0, 200.0), (20.0, 300.0),
                    (30.0, 380.0), (60.0, 0.0)),
    ),
    "large_step": Scenario(
        "large_step", "Large motor start: 0 -> 90% load in one step",
        duration=60.0,
        load_steps=((5.0, 360.0),),
    ),
}


@dataclass
class Config:
    generator: GeneratorParams
    thresholds: dict[str, Thresholds]


def load_config(path: str | Path) -> Config:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {f.name for f in fields(GeneratorParams)}
    unknown = set(data.get("generator", {})) - allowed
    if unknown:
        raise ValueError(f"unknown generator parameters: {sorted(unknown)}")
    gen = GeneratorParams(**data.get("generator", {}))
    alarms = data.get("alarms", {})
    missing = set(CHANNELS) - set(alarms)
    if missing:
        raise ValueError(f"config is missing alarm settings for: {sorted(missing)}")
    return Config(gen, {ch: Thresholds(**alarms[ch]) for ch in CHANNELS})


@dataclass
class SimResult:
    scenario: Scenario
    samples: list[Sample]
    events: list[AlarmEvent]
    thresholds: dict[str, Thresholds]


def run(scenario: Scenario, config: Config, dt: float = 0.1,
        noise: float = 0.0, seed: int | None = None) -> SimResult:
    if dt <= 0:
        raise ValueError("dt must be positive")
    gen = Generator(config.generator, noise=noise, seed=seed)
    alarms = AlarmManager.from_thresholds(config.thresholds)
    steps = sorted(scenario.load_steps)
    next_step = 0
    samples: list[Sample] = []

    for k in range(int(round(scenario.duration / dt)) + 1):
        t = k * dt
        while next_step < len(steps) and steps[next_step][0] <= t + 1e-9:
            gen.set_load(steps[next_step][1])
            next_step += 1
        sample = gen.step(t, dt)
        samples.append(sample)
        alarms.update(t, {ch: sample.value(ch) for ch in CHANNELS})

    return SimResult(scenario, samples, alarms.log, config.thresholds)


def write_csv(result: SimResult, path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["t_s", "load_kw", "voltage_v", "current_a",
                         "frequency_hz", "temperature_c"])
        for s in result.samples:
            writer.writerow([f"{s.t:.2f}", f"{s.load_kw:.1f}", f"{s.voltage:.2f}",
                             f"{s.current:.2f}", f"{s.frequency:.3f}",
                             f"{s.temperature:.2f}"])
