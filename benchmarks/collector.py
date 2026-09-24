from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class PhaseResult:
    phase: str
    command: list[str]
    duration_seconds: float
    exit_code: int
    max_rss_kb: int | None
    stdout: str
    stderr: str


def _run_timed(command: list[str], cwd: Path, env: dict[str, str]) -> PhaseResult:
    started = time.perf_counter()
    rss_kb: int | None = None

    if shutil.which("/usr/bin/time"):
        with tempfile.NamedTemporaryFile(prefix="tofu-bench-rss-", delete=False) as tmp:
            rss_file = Path(tmp.name)
        wrapped = ["/usr/bin/time", "-f", "%M", "-o", str(rss_file), *command]
        completed = subprocess.run(wrapped, cwd=cwd, env=env, capture_output=True, text=True)
        if rss_file.exists():
            value = rss_file.read_text(encoding="utf-8").strip()
            rss_file.unlink(missing_ok=True)
            if value.isdigit():
                rss_kb = int(value)
    else:
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)

    finished = time.perf_counter()
    return PhaseResult(
        phase="",
        command=command,
        duration_seconds=finished - started,
        exit_code=completed.returncode,
        max_rss_kb=rss_kb,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _state_size_bytes(cwd: Path) -> int | None:
    state_file = cwd / "terraform.tfstate"
    if not state_file.exists():
        return None
    return state_file.stat().st_size


def run_lifecycle(
    experiment_dir: Path,
    parallelism: int,
    var_args: list[str],
    run_destroy: bool = True,
    on_phase: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    env = os.environ.copy()

    phases: list[tuple[str, list[str]]] = [
        ("init", ["tofu", "init", "-input=false", "-no-color"]),
        (
            "plan_initial",
            [
                "tofu",
                "plan",
                "-input=false",
                "-no-color",
                "-parallelism",
                str(parallelism),
                "-out=tfplan",
                *var_args,
            ],
        ),
        (
            "apply",
            [
                "tofu",
                "apply",
                "-input=false",
                "-no-color",
                "-parallelism",
                str(parallelism),
                "-auto-approve",
                "tfplan",
            ],
        ),
        (
            "plan_refresh_false",
            [
                "tofu",
                "plan",
                "-input=false",
                "-no-color",
                "-parallelism",
                str(parallelism),
                "-refresh=false",
                *var_args,
            ],
        ),
        (
            "plan_refresh_true",
            [
                "tofu",
                "plan",
                "-input=false",
                "-no-color",
                "-parallelism",
                str(parallelism),
                "-refresh=true",
                *var_args,
            ],
        ),
    ]

    if run_destroy:
        phases.append(
            (
                "destroy",
                [
                    "tofu",
                    "destroy",
                    "-input=false",
                    "-no-color",
                    "-parallelism",
                    str(parallelism),
                    "-auto-approve",
                    *var_args,
                ],
            )
        )

    results: list[dict[str, Any]] = []
    failed_phase: str | None = None

    for name, command in phases:
        phase_result = _run_timed(command, cwd=experiment_dir, env=env)
        phase_result.phase = name
        phase_record = {
            "phase": name,
            "command": command,
            "duration_seconds": phase_result.duration_seconds,
            "exit_code": phase_result.exit_code,
            "max_rss_kb": phase_result.max_rss_kb,
            "stdout": phase_result.stdout,
            "stderr": phase_result.stderr,
            "state_size_bytes": _state_size_bytes(experiment_dir),
        }
        results.append(phase_record)
        if on_phase is not None:
            on_phase(phase_record)

        if phase_result.exit_code != 0 and name != "destroy":
            failed_phase = name
            break

    if failed_phase and run_destroy:
        cleanup = _run_timed(
            [
                "tofu",
                "destroy",
                "-input=false",
                "-no-color",
                "-parallelism",
                str(parallelism),
                "-auto-approve",
                *var_args,
            ],
            cwd=experiment_dir,
            env=env,
        )
        cleanup.phase = "destroy_cleanup"
        cleanup_record = {
            "phase": "destroy_cleanup",
            "command": cleanup.command,
            "duration_seconds": cleanup.duration_seconds,
            "exit_code": cleanup.exit_code,
            "max_rss_kb": cleanup.max_rss_kb,
            "stdout": cleanup.stdout,
            "stderr": cleanup.stderr,
            "state_size_bytes": _state_size_bytes(experiment_dir),
        }
        results.append(cleanup_record)
        if on_phase is not None:
            on_phase(cleanup_record)

    return {
        "experiment_dir": str(experiment_dir),
        "failed_phase": failed_phase,
        "phases": results,
    }
