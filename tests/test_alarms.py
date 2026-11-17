import pytest

from genmon.alarms import AlarmManager, ChannelMonitor, Level, Thresholds, peak_levels


def feed(monitor, values, dt=0.1):
    """Feed values at a fixed rate; return the list of non-None events."""
    events = []
    for k, v in enumerate(values):
        e = monitor.update(k * dt, v)
        if e is not None:
            events.append(e)
    return events


HIGH = Thresholds(warn_high=100.0, crit_high=120.0, hysteresis=5.0)
LOW = Thresholds(warn_low=50.0, crit_low=40.0, hysteresis=2.0)


def test_no_event_inside_limits():
    m = ChannelMonitor("x", HIGH)
    assert feed(m, [10, 50, 99.9, 80]) == []
    assert m.level is Level.NORMAL


def test_warning_raised_on_crossing_high_limit():
    m = ChannelMonitor("x", HIGH)
    events = feed(m, [90, 100])
    assert len(events) == 1
    assert (events[0].previous, events[0].level) == (Level.NORMAL, Level.WARNING)


def test_hysteresis_prevents_chatter_around_limit():
    m = ChannelMonitor("x", HIGH)
    events = feed(m, [101, 99, 101, 98, 101, 96])
    assert len(events) == 1          # raised once, never cleared (stays above 95)
    assert m.level is Level.WARNING


def test_clears_only_below_limit_minus_hysteresis():
    m = ChannelMonitor("x", HIGH)
    feed(m, [101])
    assert m.update(1.0, 95.1) is None
    event = m.update(1.1, 95.0 - 1e-6)
    assert event is not None and event.level is Level.NORMAL


def test_escalates_and_deescalates_through_levels():
    m = ChannelMonitor("x", HIGH)
    events = feed(m, [110, 125, 117, 110, 90])
    assert [(e.previous, e.level) for e in events] == [
        (Level.NORMAL, Level.WARNING),
        (Level.WARNING, Level.CRITICAL),
        # 117 is above 120-5, so CRITICAL holds; 110 drops back to WARNING
        (Level.CRITICAL, Level.WARNING),
        (Level.WARNING, Level.NORMAL),
    ]


def test_low_side_limits():
    m = ChannelMonitor("x", LOW)
    events = feed(m, [60, 49, 39, 41, 43, 53])
    assert [e.level for e in events] == [
        Level.WARNING, Level.CRITICAL, Level.WARNING, Level.NORMAL]


def test_on_delay_ignores_short_transient():
    th = Thresholds(warn_high=100.0, delay=0.5)
    m = ChannelMonitor("x", th)
    # 0.4 s above the limit (4 samples at 0.1 s) - shorter than the delay
    assert feed(m, [90, 105, 105, 105, 105, 90]) == []


def test_on_delay_raises_after_persisting():
    th = Thresholds(warn_high=100.0, delay=0.5)
    m = ChannelMonitor("x", th)
    events = feed(m, [90] + [105] * 10)
    assert len(events) == 1
    # first sample above the limit at t=0.1, raised 0.5 s later
    assert events[0].t == pytest.approx(0.6)


def test_on_delay_restarts_after_dip_below_limit():
    th = Thresholds(warn_high=100.0, delay=0.5)
    m = ChannelMonitor("x", th)
    assert feed(m, [105, 105, 105, 90, 105, 105, 105]) == []


@pytest.mark.parametrize("kwargs", [
    {"hysteresis": -1.0},
    {"delay": -0.1},
    {"warn_high": 100.0, "crit_high": 90.0},
    {"warn_low": 50.0, "crit_low": 60.0},
])
def test_invalid_thresholds_rejected(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)


def test_manager_tracks_overall_level_and_log():
    mgr = AlarmManager.from_thresholds({"a": HIGH, "b": LOW})
    mgr.update(0.0, {"a": 50, "b": 60})
    assert mgr.overall is Level.NORMAL
    mgr.update(0.1, {"a": 105, "b": 35})
    assert mgr.levels() == {"a": Level.WARNING, "b": Level.CRITICAL}
    assert mgr.overall is Level.CRITICAL
    assert peak_levels(mgr.log) == {"a": Level.WARNING, "b": Level.CRITICAL}
