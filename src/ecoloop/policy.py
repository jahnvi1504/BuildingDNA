from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


class PolicyMode(str, Enum):
    ENERGY_SAVER = "Energy Saver"
    BALANCED = "Balanced"
    COMFORT_PRIORITY = "Comfort Priority"


@dataclass(frozen=True, slots=True)
class ModeProfile:
    comfort_band: tuple[float, float]
    max_setpoint_drift_c: float
    description: str


MODE_PROFILES = {
    PolicyMode.ENERGY_SAVER: ModeProfile(
        comfort_band=(-0.5, 0.5),
        max_setpoint_drift_c=1.5,
        description="Widest safe drift for energy and carbon reduction.",
    ),
    PolicyMode.BALANCED: ModeProfile(
        comfort_band=(-0.4, 0.4),
        max_setpoint_drift_c=1.0,
        description="Equal emphasis on efficiency and occupied comfort.",
    ),
    PolicyMode.COMFORT_PRIORITY: ModeProfile(
        comfort_band=(-0.3, 0.3),
        max_setpoint_drift_c=0.5,
        description="Narrow comfort target with conservative setpoint drift.",
    ),
}

MODE_ORDER = [
    PolicyMode.COMFORT_PRIORITY,
    PolicyMode.BALANCED,
    PolicyMode.ENERGY_SAVER,
]


def policy_score(
    energy_saved_pct: float,
    comfort_improvement_pct: float,
    carbon_avoided_pct: float,
) -> float:
    return (
        0.45 * energy_saved_pct
        + 0.35 * comfort_improvement_pct
        + 0.20 * carbon_avoided_pct
    )


@dataclass(slots=True)
class PolicyState:
    mode: PolicyMode = PolicyMode.BALANCED
    episode_count: int = 0
    rolling_score: float = 0.0


class MacroPolicy:
    """Scored state machine that selects constraints for Tier 2.

    It never writes actuators. Its only output is a named policy profile that a
    reason-layer wrapper may include in Tier 2 context.
    """

    def __init__(self, state: PolicyState | None = None) -> None:
        self.state = state or PolicyState()
        self._scores: deque[float] = deque(maxlen=3)

    @property
    def profile(self) -> ModeProfile:
        return MODE_PROFILES[self.state.mode]

    def context(self) -> dict[str, Any]:
        return {
            "mode": self.state.mode.value,
            "episode": self.state.episode_count,
            "rolling_score": round(self.state.rolling_score, 4),
            **asdict(self.profile),
        }

    def complete_episode(self, score: float) -> tuple[PolicyMode, str]:
        previous_mode = self.state.mode
        self._scores.append(score)
        self.state.episode_count += 1
        self.state.rolling_score = sum(self._scores) / len(self._scores)

        reason = "Holding mode while the score trend establishes."
        if len(self._scores) == 3:
            first, second, third = self._scores
            mode_index = MODE_ORDER.index(self.state.mode)
            if first > second > third and mode_index > 0:
                self.state.mode = MODE_ORDER[mode_index - 1]
                reason = "Score declined for two episodes; stepped toward comfort."
            elif first < second < third and mode_index < len(MODE_ORDER) - 1:
                self.state.mode = MODE_ORDER[mode_index + 1]
                reason = "Score improved for two episodes; allowed a more aggressive policy."
            else:
                reason = "Score trend did not justify a mode switch."

        if self.state.mode != previous_mode:
            reason += f" Mode changed from {previous_mode.value} to {self.state.mode.value}."
        return self.state.mode, reason


class PolicyReasonWrapper:
    """Observe episode metrics, add policy context, then delegate to Tier 2.

    The wrapper has no access to EnergyPlus actuators or the Tier 1 controller.
    """

    def __init__(
        self,
        reason_agent: Any,
        baseline_path: Path,
        log_path: Path,
        episode_hours: int = 48,
    ) -> None:
        self.reason_agent = reason_agent
        self.log_path = log_path
        self.episode_hours = episode_hours
        self.policy = MacroPolicy()
        self.baseline = _hourly_endpoints(baseline_path) if baseline_path.exists() else pd.DataFrame()
        self._last_episode = 0
        self._previous_agent = {"energy_kwh": 0.0, "carbon_kg": 0.0, "comfort_violations": 0}
        self._previous_baseline = {
            "energy_kwh": 0.0,
            "carbon_kg": 0.0,
            "comfort_violations": 0,
        }
        self._log_started = False

    def observe(self, snapshot: dict[str, Any]) -> None:
        hour = max(
            0,
            (int(snapshot["day_of_year"]) - 1) * 24
            + int(snapshot["hour"])
            + int(snapshot["minute"]) // 60,
        )
        episode = hour // self.episode_hours
        if episode > self._last_episode and not self.baseline.empty:
            self._complete_episode(snapshot, hour, episode)
        enriched = {
            **snapshot,
            "macro_policy": {
                **self.policy.context(),
                "instruction": (
                    "Operate within this PMV band and maximum setpoint drift; "
                    "Tier 1 remains final safety authority."
                ),
            },
        }
        self.reason_agent.observe(enriched)

    def trigger(self) -> bool:
        return bool(self.reason_agent.trigger())

    def _complete_episode(
        self, snapshot: dict[str, Any], hour: int, episode: int
    ) -> None:
        baseline_rows = self.baseline[self.baseline["hour_bin"] <= hour]
        if baseline_rows.empty:
            return
        baseline = baseline_rows.iloc[-1]
        agent_now = {
            "energy_kwh": float(snapshot["energy_kwh"]),
            "carbon_kg": float(snapshot["carbon_kg"]),
            "comfort_violations": int(snapshot["comfort_violation_count"]),
        }
        baseline_now = {
            "energy_kwh": float(baseline["energy_kwh"]),
            "carbon_kg": float(baseline["carbon_kg"]),
            "comfort_violations": int(baseline["comfort_violations"]),
        }
        agent_delta = {
            key: agent_now[key] - self._previous_agent[key] for key in agent_now
        }
        baseline_delta = {
            key: baseline_now[key] - self._previous_baseline[key] for key in baseline_now
        }
        energy_saved_pct = 100 * (
            baseline_delta["energy_kwh"] - agent_delta["energy_kwh"]
        ) / max(baseline_delta["energy_kwh"], 1e-9)
        carbon_avoided_pct = 100 * (
            baseline_delta["carbon_kg"] - agent_delta["carbon_kg"]
        ) / max(baseline_delta["carbon_kg"], 1e-9)
        comfort_improvement_pct = 100 * (
            baseline_delta["comfort_violations"] - agent_delta["comfort_violations"]
        ) / max(baseline_delta["comfort_violations"], 1)
        score = policy_score(
            energy_saved_pct, comfort_improvement_pct, carbon_avoided_pct
        )
        mode, reason = self.policy.complete_episode(score)
        event = {
            "episode": episode,
            "simulated_hour": hour,
            "mode": mode.value,
            "score": round(score, 4),
            "rolling_score": round(self.policy.state.rolling_score, 4),
            "energy_kwh": round(agent_now["energy_kwh"], 4),
            "comfort_violations": agent_now["comfort_violations"],
            "carbon_kg": round(agent_now["carbon_kg"], 4),
            "energy_saved_pct": round(energy_saved_pct, 4),
            "comfort_improvement_pct": round(comfort_improvement_pct, 4),
            "carbon_avoided_pct": round(carbon_avoided_pct, 4),
            "reason": reason,
            "profile": asdict(MODE_PROFILES[mode]),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "a" if self._log_started else "w"
        with self.log_path.open(write_mode, encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        self._log_started = True
        self._last_episode = episode
        self._previous_agent = agent_now
        self._previous_baseline = baseline_now


def _hourly_endpoints(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["sim_hour"] = (
        (frame["day_of_year"] - 1) * 24 + frame["hour"] + frame["minute"] / 60
    )
    frame["sim_hour"] = frame["sim_hour"].clip(lower=0, upper=8759.999)
    frame["hour_bin"] = frame["sim_hour"].astype(int)
    return (
        frame.groupby("hour_bin", as_index=False)
        .agg(
            energy_kwh=("energy_kwh", "max"),
            carbon_kg=("carbon_kg", "max"),
            comfort_violations=("comfort_violation_count", "max"),
        )
        .sort_values("hour_bin")
    )


def _episode_deltas(frame: pd.DataFrame, episode_hours: int) -> pd.DataFrame:
    working = frame.copy()
    working["episode"] = working["hour_bin"] // episode_hours + 1
    endpoints = working.groupby("episode", as_index=False).agg(
        simulated_hour=("hour_bin", "max"),
        energy_kwh=("energy_kwh", "max"),
        carbon_kg=("carbon_kg", "max"),
        comfort_violations=("comfort_violations", "max"),
        samples=("hour_bin", "size"),
    )
    for column in ("energy_kwh", "carbon_kg", "comfort_violations"):
        endpoints[f"episode_{column}"] = endpoints[column].diff().fillna(endpoints[column])
    return endpoints[endpoints["samples"] >= episode_hours * 0.9]


def build_policy_log(
    baseline_path: Path,
    agent_path: Path,
    output_path: Path,
    episode_hours: int = 48,
) -> list[dict[str, Any]]:
    if episode_hours < 24:
        raise ValueError("episode_hours must be at least 24")
    baseline = _episode_deltas(_hourly_endpoints(baseline_path), episode_hours)
    agent = _episode_deltas(_hourly_endpoints(agent_path), episode_hours)
    joined = baseline.merge(agent, on="episode", suffixes=("_baseline", "_agent"))
    policy = MacroPolicy()
    events: list[dict[str, Any]] = []

    for row in joined.itertuples(index=False):
        energy_saved_pct = 100 * (
            row.episode_energy_kwh_baseline - row.episode_energy_kwh_agent
        ) / max(row.episode_energy_kwh_baseline, 1e-9)
        carbon_avoided_pct = 100 * (
            row.episode_carbon_kg_baseline - row.episode_carbon_kg_agent
        ) / max(row.episode_carbon_kg_baseline, 1e-9)
        comfort_improvement_pct = 100 * (
            row.episode_comfort_violations_baseline
            - row.episode_comfort_violations_agent
        ) / max(row.episode_comfort_violations_baseline, 1)
        score = policy_score(
            energy_saved_pct,
            comfort_improvement_pct,
            carbon_avoided_pct,
        )
        mode, reason = policy.complete_episode(score)
        events.append(
            {
                "episode": int(row.episode),
                "simulated_hour": int(row.simulated_hour_agent),
                "mode": mode.value,
                "score": round(score, 4),
                "rolling_score": round(policy.state.rolling_score, 4),
                "energy_kwh": round(float(row.energy_kwh_agent), 4),
                "comfort_violations": int(row.comfort_violations_agent),
                "carbon_kg": round(float(row.carbon_kg_agent), 4),
                "energy_saved_pct": round(energy_saved_pct, 4),
                "comfort_improvement_pct": round(comfort_improvement_pct, 4),
                "carbon_avoided_pct": round(carbon_avoided_pct, 4),
                "reason": reason,
                "profile": asdict(MODE_PROFILES[mode]),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return events
