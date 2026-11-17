from pathlib import Path

import pytest

from genmon.__main__ import main
from genmon.alarms import Level, peak_levels
from genmon.simulation import SCENARIOS, load_config, run

CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.json"


@pytest.fixture(scope="module")
def config():
    return load_config(CONFIG)


def peaks(name, config):
    return peak_levels(run(SCENARIOS[name], config).events)


def test_normal_operation_raises_no_alarms(config):
    assert peaks("normal", config) == {}


def test_overload_trips_current_then_temperature(config):
    result = run(SCENARIOS["overload"], config)
    p = peak_levels(result.events)
    assert p["current"] is Level.CRITICAL
    assert p["temperature"] is Level.CRITICAL
    first = {}
    for e in result.events:
        first.setdefault((e.channel, e.level), e.t)
    # current responds within seconds; the winding heats over minutes
    assert first[("current", Level.CRITICAL)] < 40
    assert first[("temperature", Level.WARNING)] > first[("current", Level.CRITICAL)] + 60


def test_overload_alarms_clear_after_load_shed(config):
    result = run(SCENARIOS["overload"], config)
    final = {}
    for e in result.events:
        final[e.channel] = e.level
    assert all(level is Level.NORMAL for level in final.values())


def test_load_rejection_trips_overfrequency(config):
    result = run(SCENARIOS["load_rejection"], config)
    over = [e for e in result.events
            if e.channel == "frequency" and e.level is Level.CRITICAL and e.value > 60]
    assert over, "expected a critical over-frequency alarm"


@pytest.mark.parametrize("seed", range(5))
def test_noise_does_not_cause_alarm_chatter(config, seed):
    """With 0.1% measurement noise, an alarm may be raised on a load step,
    but hysteresis must stop it re-raising: at most one raise from NORMAL
    per channel per load step."""
    scenario = SCENARIOS["normal"]
    result = run(scenario, config, noise=0.001, seed=seed)
    step_times = [t for t, _ in scenario.load_steps]
    raises = {}
    for e in result.events:
        if e.previous is Level.NORMAL:
            step = sum(1 for t in step_times if t <= e.t + 1e-9)
            key = (e.channel, step)
            raises[key] = raises.get(key, 0) + 1
    assert all(n == 1 for n in raises.values()), raises
    assert all(e.level is not Level.CRITICAL for e in result.events)


def test_cli_writes_csv_and_plot(tmp_path, capsys):
    csv_path, png_path = tmp_path / "out.csv", tmp_path / "out.png"
    assert main(["--scenario", "overload", "--csv", str(csv_path),
                 "--plot", str(png_path)]) == 0
    assert csv_path.read_text().startswith("t_s,load_kw")
    assert png_path.stat().st_size > 10_000
    assert "current" in capsys.readouterr().out


def test_config_rejects_unknown_parameter(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"generator": {"rated_mw": 1}, "alarms": {}}')
    with pytest.raises(ValueError, match="unknown generator parameters"):
        load_config(bad)
