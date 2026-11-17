"""Dashboard-style trend plot of a simulation run."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .alarms import Level  # noqa: E402
from .simulation import CHANNELS, SimResult  # noqa: E402

UNITS = {"voltage": "V", "current": "A", "frequency": "Hz", "temperature": "°C"}
LEVEL_COLORS = {Level.WARNING: "#e69500", Level.CRITICAL: "#d62728"}


def plot_result(result: SimResult, path: str | Path) -> None:
    t = [s.t for s in result.samples]
    fig, axes = plt.subplots(len(CHANNELS) + 1, 1, figsize=(11, 11), sharex=True)
    fig.suptitle(f"Generator monitor - scenario: {result.scenario.name}\n"
                 f"{result.scenario.description}", fontsize=12)

    load_ax = axes[0]
    load_ax.step(t, [s.load_kw for s in result.samples], where="post", color="#444")
    load_ax.set_ylabel("Load (kW)")
    load_ax.grid(alpha=0.3)

    for ax, ch in zip(axes[1:], CHANNELS):
        ax.plot(t, [s.value(ch) for s in result.samples], color="#1f77b4", lw=1.2)
        th = result.thresholds[ch]
        for limit, lvl in ((th.warn_high, Level.WARNING), (th.warn_low, Level.WARNING),
                           (th.crit_high, Level.CRITICAL), (th.crit_low, Level.CRITICAL)):
            if limit is not None:
                ax.axhline(limit, ls="--", lw=0.9, color=LEVEL_COLORS[lvl])
        _shade_alarms(ax, result, ch, t[-1])
        ax.set_ylabel(f"{ch.capitalize()} ({UNITS[ch]})")
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _shade_alarms(ax, result: SimResult, channel: str, t_end: float) -> None:
    """Shade the periods during which ``channel`` was in WARNING or CRITICAL."""
    level, since = Level.NORMAL, 0.0
    for e in (e for e in result.events if e.channel == channel):
        if level != Level.NORMAL:
            ax.axvspan(since, e.t, color=LEVEL_COLORS[level], alpha=0.15, lw=0)
        level, since = e.level, e.t
    if level != Level.NORMAL:
        ax.axvspan(since, t_end, color=LEVEL_COLORS[level], alpha=0.15, lw=0)
