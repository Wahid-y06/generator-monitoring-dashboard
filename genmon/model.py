"""Simplified three-phase generator model.

The model is intentionally small: it captures the behaviour an operator
actually watches on a genset panel (voltage/frequency dips on load steps,
current proportional to load, slow winding temperature rise) without
solving full machine equations.

Dynamics
--------
* A load step of dP (per-unit of rated kW) produces an instantaneous
  frequency deviation of ``-inertia_dip_hz_per_pu * dP`` and a voltage
  deviation of ``-voltage_dip_pu_per_pu * dP``. Load *rejection* (dP < 0)
  therefore produces an over-frequency / over-voltage transient.
* The governor (isochronous) and AVR pull those deviations back to zero
  with first-order time constants ``governor_tau`` and ``avr_tau``.
* Line current is computed from real power: I = P / (sqrt(3) * V * pf).
* Winding temperature follows a first-order thermal model whose steady
  state rises with (I / I_rated)^2, since copper losses scale with I^2.

Each first-order update uses the exact discretisation exp(-dt/tau), so the
frequency and voltage recovery are exact at any time step. The temperature
input (current) is held constant over a step, so coarse steps add a small
error while the voltage is still recovering.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

SQRT3 = math.sqrt(3.0)


@dataclass(frozen=True)
class GeneratorParams:
    rated_kva: float = 500.0
    rated_voltage: float = 480.0          # line-to-line, V
    nominal_freq: float = 60.0            # Hz
    power_factor: float = 0.8
    governor_tau: float = 2.0             # s, frequency recovery time constant
    avr_tau: float = 0.5                  # s, voltage recovery time constant
    inertia_dip_hz_per_pu: float = 3.0    # Hz dip per 1.0 pu load step
    voltage_dip_pu_per_pu: float = 0.15   # pu voltage dip per 1.0 pu load step
    ambient_c: float = 25.0
    temp_rise_full_load_c: float = 80.0   # steady-state rise at rated current
    thermal_tau: float = 120.0            # s

    @property
    def rated_kw(self) -> float:
        return self.rated_kva * self.power_factor

    @property
    def rated_current(self) -> float:
        return self.rated_kva * 1000.0 / (SQRT3 * self.rated_voltage)


@dataclass(frozen=True)
class Sample:
    t: float
    load_kw: float
    voltage: float
    current: float
    frequency: float
    temperature: float

    def value(self, channel: str) -> float:
        return getattr(self, channel)


class Generator:
    """Discrete-time generator simulation.

    ``noise`` is the relative standard deviation of Gaussian measurement
    noise added to each reading (0.0 disables noise). Noise affects only
    the reported measurements, never the internal state.
    """

    def __init__(self, params: GeneratorParams | None = None,
                 noise: float = 0.0, seed: int | None = None) -> None:
        self.p = params or GeneratorParams()
        self.noise = noise
        self._rng = random.Random(seed)
        self._load_kw = 0.0
        self._df = 0.0          # frequency deviation, Hz
        self._dv = 0.0          # voltage deviation, pu
        self._temp = self.p.ambient_c

    @property
    def load_kw(self) -> float:
        return self._load_kw

    def set_load(self, kw: float) -> None:
        kw = max(0.0, float(kw))
        dp = (kw - self._load_kw) / self.p.rated_kw
        self._df -= self.p.inertia_dip_hz_per_pu * dp
        self._dv -= self.p.voltage_dip_pu_per_pu * dp
        self._load_kw = kw

    def _true_values(self) -> tuple[float, float, float]:
        voltage = self.p.rated_voltage * (1.0 + self._dv)
        frequency = self.p.nominal_freq + self._df
        current = (self._load_kw * 1000.0 / (SQRT3 * voltage * self.p.power_factor)
                   if voltage > 0 else 0.0)
        return voltage, frequency, current

    def _measure(self, x: float) -> float:
        if self.noise <= 0:
            return x
        return x * (1.0 + self._rng.gauss(0.0, self.noise))

    def step(self, t: float, dt: float) -> Sample:
        """Return the reading at time ``t``, then advance the state by ``dt``."""
        voltage, frequency, current = self._true_values()
        sample = Sample(
            t=t,
            load_kw=self._load_kw,
            voltage=self._measure(voltage),
            current=self._measure(current),
            frequency=self._measure(frequency),
            temperature=self._measure(self._temp),
        )

        p = self.p
        self._df *= math.exp(-dt / p.governor_tau)
        self._dv *= math.exp(-dt / p.avr_tau)
        temp_ss = p.ambient_c + p.temp_rise_full_load_c * (current / p.rated_current) ** 2
        self._temp += (temp_ss - self._temp) * (1.0 - math.exp(-dt / p.thermal_tau))
        return sample
