from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path
from typing import Any


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if len(values) == 1:
        return values[0]

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def bootstrap_ci_mean(
    samples: list[float],
    confidence: float = 0.95,
    resamples: int = 2000,
    seed: int = 42,
) -> tuple[float, float]:
    if not samples:
        raise ValueError("samples must not be empty")
    if len(samples) == 1:
        return samples[0], samples[0]

    rng = random.Random(seed)
    means: list[float] = []
    alpha = (1.0 - confidence) / 2.0

    for _ in range(resamples):
        drawn = rng.choices(samples, k=len(samples))
        means.append(statistics.fmean(drawn))

    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)


def aggregate(raw: dict[str, Any], confidence: float = 0.95, resamples: int = 2000) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    for run in raw["runs"]:
        exp = run["experiment"]
        for phase in run["lifecycle"]["phases"]:
            rows.append(
                {
                    "config": exp["config_name"],
                    "experiment": exp["experiment_name"],
                    "phase": phase["phase"],
                    "duration_seconds": phase["duration_seconds"],
                    "exit_code": phase["exit_code"],
                }
            )

    grouped: dict[tuple[str, str, str], list[float]] = {}
    for row in rows:
        if row["exit_code"] != 0:
            continue
        key = (row["experiment"], row["config"], row["phase"])
        grouped.setdefault(key, []).append(row["duration_seconds"])

    summaries: list[dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        samples = grouped[key]
        mean = statistics.fmean(samples)
        median = statistics.median(samples)
        stddev = statistics.stdev(samples) if len(samples) > 1 else 0.0
        ci_low, ci_high = bootstrap_ci_mean(samples, confidence=confidence, resamples=resamples)

        summaries.append(
            {
                "experiment": key[0],
                "config": key[1],
                "phase": key[2],
                "n": len(samples),
                "mean_seconds": mean,
                "median_seconds": median,
                "stddev_seconds": stddev,
                "ci_confidence": confidence,
                "ci_low_seconds": ci_low,
                "ci_high_seconds": ci_high,
            }
        )

    return {
        "meta": {
            "confidence": confidence,
            "resamples": resamples,
            "total_runs": len(raw["runs"]),
        },
        "summary": summaries,
    }


def to_markdown(aggregate_data: dict[str, Any]) -> str:
    headers = [
        "experiment",
        "config",
        "phase",
        "n",
        "mean_s",
        "median_s",
        "stddev_s",
        "ci95_low_s",
        "ci95_high_s",
    ]

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for item in aggregate_data["summary"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    item["experiment"],
                    item["config"],
                    item["phase"],
                    str(item["n"]),
                    f"{item['mean_seconds']:.4f}",
                    f"{item['median_seconds']:.4f}",
                    f"{item['stddev_seconds']:.4f}",
                    f"{item['ci_low_seconds']:.4f}",
                    f"{item['ci_high_seconds']:.4f}",
                ]
            )
            + " |"
        )

    return "\n".join(lines) + "\n"


def write_reports(raw: dict[str, Any], aggregate_path: Path, markdown_path: Path, confidence: float, resamples: int) -> None:
    aggregate_data = aggregate(raw, confidence=confidence, resamples=resamples)
    aggregate_path.write_text(json.dumps(aggregate_data, indent=2), encoding="utf-8")
    markdown_path.write_text(to_markdown(aggregate_data), encoding="utf-8")
