from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from collector import run_lifecycle
from report import write_reports


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "experiments"
RESULTS_DIR = ROOT / "benchmarks" / "results"


def _docker_warmup(images: list[str]) -> None:
    for image in images:
        subprocess.run(["docker", "pull", image], check=True)


def _var_flags(values: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    for key, value in values.items():
        flags.extend(["-var", f"{key}={value}"])
    return flags


def _print_run_header(
    run_index: int, total_runs: int, experiment_name: str, config_name: str, iteration: int, iterations: int
) -> None:
    print(f"[{run_index}/{total_runs}] {experiment_name}/{config_name} iter {iteration}/{iterations}", flush=True)


def _print_phase(phase_record: dict[str, Any]) -> None:
    status = "ok" if phase_record["exit_code"] == 0 else f"FAILED exit={phase_record['exit_code']}"
    print(f"    {phase_record['phase']:<20} {phase_record['duration_seconds']:>7.2f}s  {status}", flush=True)


def _matrix() -> list[dict[str, Any]]:
    return [
        {
            "experiment_name": "01-environments",
            "configs": [
                {
                    "config_name": "minimal",
                    "dir": EXPERIMENTS_DIR / "01-environments",
                    "vars": {
                        "env_name": "bench-min",
                        "environment_type": "minimal",
                    },
                },
                {
                    "config_name": "two-tier",
                    "dir": EXPERIMENTS_DIR / "01-environments",
                    "vars": {
                        "env_name": "bench-tier",
                        "environment_type": "two-tier",
                        "gateway_port": 18080,
                    },
                },
                {
                    "config_name": "multi-worker",
                    "dir": EXPERIMENTS_DIR / "01-environments",
                    "vars": {
                        "env_name": "bench-multi",
                        "environment_type": "multi-worker",
                        "worker_count": 8,
                        "ingress_port": 19080,
                    },
                },
            ],
        },
        {
            "experiment_name": "02-scale-wide",
            "configs": [
                {
                    "config_name": f"count-{count}",
                    "dir": EXPERIMENTS_DIR / "02-scale-wide",
                    "vars": {
                        "env_name": f"bench-wide-{count}",
                        "container_count": count,
                    },
                }
                for count in [5, 20, 50, 100]
            ],
        },
        {
            "experiment_name": "03-encryption",
            "configs": [
                {
                    "config_name": "encrypted-baseline",
                    "dir": EXPERIMENTS_DIR / "03-encryption",
                    "vars": {
                        "env_name": "bench-encrypted",
                        "encryption_passphrase": "tofu-benchmark-local-passphrase",
                    },
                }
            ],
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenTofu benchmark runner")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--parallelism", type=int, default=10)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--experiments",
        type=str,
        default="",
        help="Comma-separated experiment names (01-environments,02-scale-wide,03-encryption)",
    )
    args = parser.parse_args()

    selected = {name.strip() for name in args.experiments.split(",") if name.strip()}
    matrix = [item for item in _matrix() if not selected or item["experiment_name"] in selected]

    if args.dry_run:
        print(json.dumps(matrix, indent=2, default=str))
        return 0

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _docker_warmup(["alpine:3.20", "nginx:1.27-alpine"])

    total_runs = sum(len(experiment["configs"]) * args.iterations for experiment in matrix)
    print(f"Benchmark plan: {len(matrix)} experiments, {total_runs} total runs\n", flush=True)

    runs: list[dict[str, Any]] = []
    run_index = 0
    suite_started = time.perf_counter()

    for experiment in matrix:
        for config in experiment["configs"]:
            for iteration in range(1, args.iterations + 1):
                run_index += 1
                _print_run_header(
                    run_index,
                    total_runs,
                    experiment["experiment_name"],
                    config["config_name"],
                    iteration,
                    args.iterations,
                )
                run_started = time.perf_counter()
                lifecycle = run_lifecycle(
                    experiment_dir=config["dir"],
                    parallelism=args.parallelism,
                    var_args=_var_flags(config["vars"]),
                    on_phase=_print_phase,
                )
                run_elapsed = time.perf_counter() - run_started
                suite_elapsed = time.perf_counter() - suite_started
                print(f"  -> run completed in {run_elapsed:.2f}s (suite elapsed {suite_elapsed:.1f}s)\n", flush=True)
                runs.append(
                    {
                        "experiment": {
                            "experiment_name": experiment["experiment_name"],
                            "config_name": config["config_name"],
                            "directory": str(config["dir"]),
                            "vars": config["vars"],
                            "iteration": iteration,
                        },
                        "lifecycle": lifecycle,
                    }
                )

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    raw_path = RESULTS_DIR / f"raw-{timestamp}.json"
    aggregate_path = RESULTS_DIR / f"aggregate-{timestamp}.json"
    markdown_path = RESULTS_DIR / f"summary-{timestamp}.md"

    raw = {
        "meta": {
            "iterations": args.iterations,
            "parallelism": args.parallelism,
            "confidence": args.confidence,
            "bootstrap_resamples": args.bootstrap_resamples,
            "generated_at_utc": timestamp,
        },
        "runs": runs,
    }

    raw_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    write_reports(
        raw=raw,
        aggregate_path=aggregate_path,
        markdown_path=markdown_path,
        confidence=args.confidence,
        resamples=args.bootstrap_resamples,
    )

    print(f"Wrote raw results: {raw_path}")
    print(f"Wrote aggregate results: {aggregate_path}")
    print(f"Wrote summary table: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
