import math

import pytest

from genmon.model import Generator, GeneratorParams


def run_for(gen, seconds, dt=0.1, t0=0.0):
    samples = []
    for k in range(int(round(seconds / dt))):
        samples.append(gen.step(t0 + k * dt, dt))
    return samples


def test_rated_current_at_rated_load():
    p = GeneratorParams()
    gen = Generator(p)
    gen.set_load(p.rated_kw)
    s = run_for(gen, 30.0)[-1]            # let voltage settle
    assert s.current == pytest.approx(p.rated_current, rel=1e-3)
    assert p.rated_current == pytest.approx(601.4, abs=0.1)


def test_load_step_dips_frequency_then_recovers():
    p = GeneratorParams()
    gen = Generator(p)
    gen.set_load(0.5 * p.rated_kw)
    samples = run_for(gen, 20.0)
    assert samples[0].frequency == pytest.approx(p.nominal_freq - 1.5)
    assert samples[0].voltage < p.rated_voltage
    assert samples[-1].frequency == pytest.approx(p.nominal_freq, abs=0.01)
    assert samples[-1].voltage == pytest.approx(p.rated_voltage, rel=1e-4)


def test_frequency_recovery_follows_governor_time_constant():
    p = GeneratorParams()
    gen = Generator(p)
    gen.set_load(p.rated_kw)
    samples = run_for(gen, 10.0)
    idx = round(p.governor_tau / 0.1)
    expected = p.inertia_dip_hz_per_pu * math.exp(-1)
    assert p.nominal_freq - samples[idx].frequency == pytest.approx(expected, rel=1e-6)


def test_load_rejection_causes_overfrequency_and_overvoltage():
    p = GeneratorParams()
    gen = Generator(p)
    gen.set_load(p.rated_kw)
    run_for(gen, 30.0)
    gen.set_load(0.0)
    s = gen.step(30.0, 0.1)
    assert s.frequency > p.nominal_freq + 2.5
    assert s.voltage > p.rated_voltage * 1.1
    assert s.current == 0.0


def test_temperature_approaches_steady_state():
    p = GeneratorParams()
    gen = Generator(p)
    gen.set_load(p.rated_kw)
    s = run_for(gen, 10 * p.thermal_tau, dt=1.0)[-1]
    assert s.temperature == pytest.approx(p.ambient_c + p.temp_rise_full_load_c, abs=0.5)


def test_frequency_exact_at_any_time_step():
    p = GeneratorParams()
    coarse, fine = Generator(p), Generator(p)
    coarse.set_load(p.rated_kw)
    fine.set_load(p.rated_kw)
    run_for(coarse, 3.0, dt=1.0)
    run_for(fine, 3.0, dt=0.01)
    assert coarse.step(3.0, 1.0).frequency == pytest.approx(
        fine.step(3.0, 0.01).frequency, rel=1e-9)


def test_temperature_converges_with_time_step():
    p = GeneratorParams()
    coarse, fine = Generator(p), Generator(p)
    coarse.set_load(p.rated_kw)
    fine.set_load(p.rated_kw)
    run_for(coarse, 60.0, dt=1.0)
    run_for(fine, 60.0, dt=0.01)
    assert coarse.step(60.0, 1.0).temperature == pytest.approx(
        fine.step(60.0, 0.01).temperature, rel=5e-3)


def test_negative_load_clamped_to_zero():
    gen = Generator()
    gen.set_load(-50)
    assert gen.load_kw == 0.0


def test_noise_is_reproducible_with_seed():
    a, b = Generator(noise=0.01, seed=42), Generator(noise=0.01, seed=42)
    for gen in (a, b):
        gen.set_load(200)
    assert run_for(a, 1.0) == run_for(b, 1.0)
