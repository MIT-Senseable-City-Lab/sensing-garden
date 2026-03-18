"""Queue management commands for bugcam."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..config import get_iphone_watch_dir, get_recordings_dir
from ..jobs import ensure_job_dirs, get_job_counts, retry_failed_jobs, run_ingest, run_process, run_upload

app = typer.Typer(help="Run and inspect the media job workflow")
console = Console()


def _print_summary(label: str, counts: dict[str, int]) -> None:
    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    console.print(f"[cyan]{label}[/cyan] {summary}")


def _run_stage(stage: str) -> dict[str, int]:
    if stage == "ingest":
        return run_ingest()
    if stage == "process":
        return run_process()
    if stage == "upload":
        return run_upload()
    if stage == "all":
        result = {}
        result.update({f"ingest_{k}": v for k, v in run_ingest().items()})
        result.update({f"process_{k}": v for k, v in run_process().items()})
        result.update({f"upload_{k}": v for k, v in run_upload().items()})
        return result
    raise ValueError(f"Unknown stage: {stage}")


def _start_record_subprocess(record_interval: int, record_length: int, record_output_dir: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "bugcam.cli",
            "record",
            "start",
            "--interval",
            str(record_interval),
            "--length",
            str(record_length),
            "--output-dir",
            str(record_output_dir),
            "--quiet",
        ],
        text=True,
    )


@app.command()
def run(
    stage: str = typer.Option("all", "--stage", help="Stage to run: ingest, process, upload, all"),
    watch: bool = typer.Option(False, "--watch", help="Keep running in a loop"),
    poll_interval: int = typer.Option(10, "--poll-interval", help="Seconds between watch iterations"),
    capture_record: bool = typer.Option(False, "--capture-record", help="Start bugcam record alongside the worker loop"),
    record_interval: int = typer.Option(10, "--record-interval", help="Recording interval in minutes when using --capture-record"),
    record_length: int = typer.Option(60, "--record-length", help="Recording length in seconds when using --capture-record"),
    record_output_dir: Optional[Path] = typer.Option(None, "--record-output-dir", help="Recording output directory when using --capture-record"),
) -> None:
    """Run queue workers once or continuously."""
    if stage not in {"ingest", "process", "upload", "all"}:
        console.print(f"[red]Invalid stage: {stage}[/red]")
        raise typer.Exit(1)

    if poll_interval < 1:
        console.print("[red]Poll interval must be at least 1 second[/red]")
        raise typer.Exit(1)

    if capture_record and stage != "all":
        console.print("[red]--capture-record requires --stage all[/red]")
        raise typer.Exit(1)

    ensure_job_dirs()
    record_process: subprocess.Popen[str] | None = None
    if capture_record:
        output_dir = record_output_dir or get_recordings_dir()
        console.print(f"[cyan]Starting record producer in {output_dir}[/cyan]")
        record_process = _start_record_subprocess(record_interval, record_length, output_dir)

    try:
        while True:
            _print_summary("run", _run_stage(stage))
            if not watch:
                break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        console.print("[yellow]Jobs worker stopped[/yellow]")
        raise typer.Exit(0)
    finally:
        if record_process is not None:
            record_process.terminate()
            record_process.wait()


@app.command()
def status() -> None:
    """Show job queue status."""
    ensure_job_dirs()
    counts = get_job_counts()
    console.print("\n[bold]bugcam job status[/bold]")
    console.print(f"  iPhone watch: [cyan]{get_iphone_watch_dir()}[/cyan]")
    console.print(f"  RPi watch:    [cyan]{get_recordings_dir()}[/cyan]")
    for label, value in counts.items():
        console.print(f"  {label:.<12} {value}")
    console.print()
    raise typer.Exit(1 if counts["failed"] else 0)


@app.command()
def retry(
    stage: Optional[str] = typer.Option(None, "--stage", help="Retry only failures from this stage: process or upload"),
    job_id: Optional[str] = typer.Option(None, "--job-id", help="Retry a specific job ID"),
) -> None:
    """Retry failed jobs."""
    if stage is not None and stage not in {"process", "upload"}:
        console.print("[red]Stage must be 'process' or 'upload'[/red]")
        raise typer.Exit(1)

    result = retry_failed_jobs(stage=stage, job_id=job_id)
    _print_summary("retry", result)
    raise typer.Exit(0 if result["retried"] else 1)
