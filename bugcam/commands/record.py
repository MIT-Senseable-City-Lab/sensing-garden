"""Video recording command for bugcam."""
import typer
import time
import signal
import platform
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime
from rich.console import Console
from typing import Optional

app = typer.Typer(help="Record videos from camera")
console = Console()

# Default output directory
DEFAULT_OUTPUT_DIR = Path.home() / "bugcam-videos"


def _check_camera_available() -> bool:
    if platform.system() != "Linux":
        return True  # Can't check on non-Linux
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-c", "from picamera2 import Picamera2; Picamera2()"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_ffmpeg_available() -> bool:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _remux_video(path: Path) -> bool:
    if not _check_ffmpeg_available():
        console.print("[yellow]ffmpeg not found, skipping remux[/yellow]")
        return True

    tmp_path = path.with_suffix('.tmp.mp4')
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-c", "copy", str(tmp_path)],
            check=True,
            capture_output=True
        )
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        console.print(f"[yellow]Remux failed: {e}[/yellow]")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def _record_single_video(output_path: Path, length: int, quiet: bool) -> bool:
    # Import here to avoid import errors on non-Pi systems
    try:
        from picamera2 import Picamera2
        from picamera2.encoders import H264Encoder
    except ImportError:
        console.print("[red]picamera2 not available. Run on Raspberry Pi.[/red]")
        return False

    try:
        picam2 = Picamera2()
        camera_config = picam2.create_video_configuration(
            main={"format": 'RGB888', "size": (1080, 1080)}
        )
        picam2.configure(camera_config)

        # Try to set autofocus controls (only available on Camera Module 3)
        try:
            picam2.set_controls({"AfMode": 0, "LensPosition": 0.5})
        except Exception:
            # Camera doesn't support autofocus (e.g., Camera Module 2, HQ Camera)
            pass

        picam2.start()

        encoder = H264Encoder(bitrate=10000000)  # 10 Mbps

        if not quiet:
            console.print(f"[cyan]Recording {length}s video...[/cyan]", end=" ")

        picam2.start_recording(encoder, str(output_path))
        time.sleep(length)
        picam2.stop_recording()
        picam2.close()

        if not quiet:
            console.print("[green]done[/green]")

        return True

    except Exception as e:
        console.print(f"[red]Recording failed: {e}[/red]")
        return False


@app.command()
def start(
    duration: int = typer.Option(0, "--duration", "-d", help="Total runtime in minutes (0 = run forever)"),
    interval: int = typer.Option(10, "--interval", "-i", help="Minutes between recordings"),
    length: int = typer.Option(60, "--length", "-l", help="Length of each video in seconds"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output-dir", "-o", help="Directory to save videos"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output"),
) -> None:
    """Start recording videos at intervals.

    Records videos of specified length at regular intervals.
    Videos are saved with timestamp filenames.
    """
    # Validate parameters
    if interval < 1:
        console.print("[red]Interval must be at least 1 minute[/red]")
        raise typer.Exit(1)

    if length < 1:
        console.print("[red]Length must be at least 1 second[/red]")
        raise typer.Exit(1)

    if length > interval * 60:
        console.print("[red]Video length cannot exceed interval[/red]")
        raise typer.Exit(1)

    # Check platform
    if platform.system() != "Linux":
        console.print("[red]Recording only works on Raspberry Pi (Linux)[/red]")
        raise typer.Exit(1)

    # Check camera
    if not _check_camera_available():
        console.print("[red]Camera not accessible[/red]")
        console.print("Run [cyan]bugcam status camera[/cyan] to diagnose.")
        raise typer.Exit(1)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Setup duration timer
    stop_flag = False

    def timeout_handler(signum, frame):
        nonlocal stop_flag
        stop_flag = True

    if duration > 0:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(duration * 60)

    # Show startup info
    if not quiet:
        console.print("\n[bold green]bugcam video recording[/bold green]\n")
        console.print(f"  Output:   [cyan]{output_dir}[/cyan]")
        console.print(f"  Interval: [cyan]{interval} min[/cyan]")
        console.print(f"  Length:   [cyan]{length} sec[/cyan]")
        if duration > 0:
            console.print(f"  Duration: [cyan]{duration} min[/cyan]")
        else:
            console.print(f"  Duration: [cyan]indefinite[/cyan]")
        console.print("\nPress [cyan]Ctrl+C[/cyan] to stop\n")

    start_time = datetime.now()
    videos_recorded = 0

    try:
        while not stop_flag:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = output_dir / f"video_{timestamp}.mp4"

            # Record video
            if _record_single_video(video_path, length, quiet):
                # Remux for compatibility
                if not quiet:
                    console.print("[dim]Remuxing...[/dim]", end=" ")
                _remux_video(video_path)
                if not quiet:
                    console.print(f"[green]Saved:[/green] {video_path.name}")
                videos_recorded += 1

            # Wait for next interval
            if not stop_flag:
                sleep_seconds = (interval * 60) - length
                if sleep_seconds > 0:
                    if not quiet:
                        console.print(f"[dim]Next recording in {sleep_seconds // 60}m {sleep_seconds % 60}s[/dim]")

                    # Sleep in chunks to allow interrupt
                    for _ in range(sleep_seconds):
                        if stop_flag:
                            break
                        time.sleep(1)

    except KeyboardInterrupt:
        if not quiet:
            console.print("\n[yellow]Recording stopped by user[/yellow]")

    finally:
        signal.alarm(0)

        # Show summary
        elapsed = datetime.now() - start_time
        elapsed_str = str(elapsed).split('.')[0]

        if not quiet:
            console.print(f"\n[bold]Recording complete[/bold]")
            console.print(f"  Videos recorded: [cyan]{videos_recorded}[/cyan]")
            console.print(f"  Runtime:         [cyan]{elapsed_str}[/cyan]")
            console.print(f"  Output:          [cyan]{output_dir}[/cyan]")


@app.command()
def single(
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    length: int = typer.Option(60, "--length", "-l", help="Length of video in seconds"),
) -> None:
    """Record a single video.

    Records one video and exits. Useful for testing.
    """
    if platform.system() != "Linux":
        console.print("[red]Recording only works on Raspberry Pi (Linux)[/red]")
        raise typer.Exit(1)

    if not _check_camera_available():
        console.print("[red]Camera not accessible[/red]")
        raise typer.Exit(1)

    # Generate output path if not specified
    if output is None:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = DEFAULT_OUTPUT_DIR / f"video_{timestamp}.mp4"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[cyan]Recording {length}s video to {output}[/cyan]")

    if _record_single_video(output, length, quiet=False):
        _remux_video(output)
        console.print(f"[green]Video saved: {output}[/green]")
    else:
        raise typer.Exit(1)
