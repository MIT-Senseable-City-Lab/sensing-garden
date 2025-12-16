"""System status and diagnostics for bugcam."""
import typer
import subprocess
import platform
from pathlib import Path
from rich.console import Console
from rich.table import Table
from ..config import get_python_for_detection, get_cache_dir

app = typer.Typer(help="Check system status and dependencies")
console = Console()


# --- Check Functions ---

def _check_python_import(import_name: str) -> bool:
    """Check if a package is importable in the detection Python interpreter."""
    if platform.system() != "Linux":
        return False
    try:
        python_exe = get_python_for_detection()
        result = subprocess.run(
            [python_exe, "-c", f"import {import_name}"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_hailo_device() -> tuple[bool, str]:
    """Test Hailo AI accelerator connection."""
    try:
        result = subprocess.run(
            ["hailortcli", "scan"],
            capture_output=True,
            timeout=10
        )
        stdout = result.stdout.decode()
        stderr = result.stderr.decode()

        if "not found" in stdout.lower() or "not found" in stderr.lower():
            return False, "No device found"

        if result.returncode == 0 and "Hailo" in stdout:
            for line in stdout.strip().split("\n"):
                if "Hailo" in line and "not found" not in line.lower():
                    return True, line.strip()
            return True, "Detected"

        return False, "Check failed"
    except FileNotFoundError:
        return False, "hailortcli not installed"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)[:50]


def _check_camera() -> tuple[bool, str]:
    """Test camera connection."""
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-c", "from picamera2 import Picamera2; Picamera2()"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, "Accessible"

        stderr = result.stderr.decode()
        if "dtype size changed" in stderr or "binary incompatibility" in stderr:
            return False, "NumPy incompatibility"
        return False, "Not accessible"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)[:50]


def _check_sensor() -> tuple[bool, str]:
    """Test I2C sensor connection."""
    i2c_device = Path("/dev/i2c-1")
    if not i2c_device.exists():
        return False, "I2C not enabled"

    try:
        result = subprocess.run(
            ["i2cdetect", "-y", "1"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            return True, "I2C enabled (scan unavailable)"

        output = result.stdout.decode()
        sensors = []
        if "61" in output:
            sensors.append("SCD30")
        if "62" in output:
            sensors.append("SCD40")
        if "76" in output or "77" in output:
            sensors.append("BME280")

        if sensors:
            return True, ", ".join(sensors)
        return False, "No sensors detected"
    except FileNotFoundError:
        return True, "I2C enabled (i2cdetect missing)"
    except Exception as e:
        return False, str(e)[:50]


def _check_models() -> tuple[bool, str]:
    """Check for installed models."""
    models_dir = get_cache_dir() / "models"
    hef_files = list(models_dir.glob("*.hef")) if models_dir.exists() else []
    if hef_files:
        return True, f"{len(hef_files)} installed"
    return False, "None installed"


def _print_status(name: str, ok: bool, detail: str) -> None:
    """Print a status row."""
    status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
    console.print(f"  {name:.<20} {status}  {detail}")


# --- Subcommands ---

@app.command()
def deps() -> None:
    """Check software dependencies."""
    console.print("\n[bold cyan]Dependencies[/bold cyan]")

    if platform.system() != "Linux":
        console.print("[yellow]  Skipped (Linux only)[/yellow]\n")
        return

    all_ok = True
    packages = [
        ("gi", "python3-gi"),
        ("hailo", "hailo-all"),
        ("hailo_apps", "bugcam setup"),
        ("numpy", "python3-numpy"),
        ("cv2", "python3-opencv"),
    ]

    for import_name, install_hint in packages:
        ok = _check_python_import(import_name)
        if not ok:
            all_ok = False
        detail = "" if ok else f"Install: {install_hint}"
        _print_status(import_name, ok, detail)

    console.print()
    raise typer.Exit(0 if all_ok else 1)


@app.command()
def devices() -> None:
    """Check hardware device connections."""
    console.print("\n[bold cyan]Devices[/bold cyan]")

    if platform.system() != "Linux":
        console.print("[yellow]  Skipped (Linux only)[/yellow]\n")
        return

    all_ok = True

    hailo_ok, hailo_detail = _check_hailo_device()
    if not hailo_ok:
        all_ok = False
    _print_status("Hailo", hailo_ok, hailo_detail)

    camera_ok, camera_detail = _check_camera()
    if not camera_ok:
        all_ok = False
    _print_status("Camera", camera_ok, camera_detail)

    sensor_ok, sensor_detail = _check_sensor()
    if not sensor_ok:
        all_ok = False
    _print_status("Sensors", sensor_ok, sensor_detail)

    console.print()
    raise typer.Exit(0 if all_ok else 1)


@app.command()
def hailo() -> None:
    """Check Hailo AI accelerator."""
    console.print("\n[bold cyan]Hailo Check[/bold cyan]")

    if platform.system() != "Linux":
        console.print("[yellow]  Skipped (Linux only)[/yellow]\n")
        return

    ok, detail = _check_hailo_device()
    if ok:
        console.print(f"[green]  ✓ {detail}[/green]")
    else:
        console.print(f"[red]  ✗ {detail}[/red]")
        console.print("\n[yellow]Troubleshooting:[/yellow]")
        console.print("  1. Check AI HAT+ is properly seated")
        console.print("  2. Enable PCIe Gen 3: [cyan]sudo raspi-config[/cyan] → Advanced → PCIe")
        console.print("  3. Reinstall: [cyan]sudo apt install --reinstall hailo-all[/cyan]")
        console.print("  4. Reboot: [cyan]sudo reboot[/cyan]")

    console.print()
    raise typer.Exit(0 if ok else 1)


@app.command()
def camera() -> None:
    """Check camera connection."""
    console.print("\n[bold cyan]Camera Check[/bold cyan]")

    if platform.system() != "Linux":
        console.print("[yellow]  Skipped (Linux only)[/yellow]\n")
        return

    ok, detail = _check_camera()
    if ok:
        console.print(f"[green]  ✓ {detail}[/green]")
    else:
        console.print(f"[red]  ✗ {detail}[/red]")
        if "NumPy" in detail:
            console.print("\n[yellow]Fix:[/yellow]")
            console.print("  [cyan]sudo apt install --reinstall python3-numpy python3-picamera2 python3-libcamera[/cyan]")

    console.print()
    raise typer.Exit(0 if ok else 1)


@app.command()
def sensor() -> None:
    """Check I2C sensor connection."""
    console.print("\n[bold cyan]Sensor Check[/bold cyan]")

    if platform.system() != "Linux":
        console.print("[yellow]  Skipped (Linux only)[/yellow]\n")
        return

    ok, detail = _check_sensor()
    if ok:
        console.print(f"[green]  ✓ {detail}[/green]")
    else:
        console.print(f"[red]  ✗ {detail}[/red]")
        if "I2C not enabled" in detail:
            console.print("\n[yellow]Enable I2C:[/yellow] [cyan]sudo raspi-config[/cyan]")

    console.print()
    raise typer.Exit(0 if ok else 1)


@app.command()
def models() -> None:
    """Check installed models."""
    console.print("\n[bold cyan]Models[/bold cyan]")

    ok, detail = _check_models()
    if ok:
        console.print(f"[green]  ✓ {detail}[/green]")
    else:
        console.print(f"[red]  ✗ {detail}[/red]")
        console.print("\n[yellow]Download:[/yellow] [cyan]bugcam models download yolov8s[/cyan]")

    console.print()
    raise typer.Exit(0 if ok else 1)


@app.callback(invoke_without_command=True)
def status(ctx: typer.Context) -> None:
    """Run all system checks."""
    if ctx.invoked_subcommand is not None:
        return

    console.print("\n[bold]bugcam system status[/bold]")

    all_ok = True

    # Dependencies
    console.print("\n[cyan]Dependencies[/cyan]")
    if platform.system() != "Linux":
        console.print("  [dim]Skipped (Linux only)[/dim]")
    else:
        for import_name, _ in [("gi", ""), ("hailo", ""), ("hailo_apps", ""), ("numpy", ""), ("cv2", "")]:
            ok = _check_python_import(import_name)
            if not ok:
                all_ok = False
            _print_status(import_name, ok, "")

    # Models
    console.print("\n[cyan]Models[/cyan]")
    models_ok, models_detail = _check_models()
    if not models_ok:
        all_ok = False
    _print_status("HEF files", models_ok, models_detail)

    # Devices
    console.print("\n[cyan]Devices[/cyan]")
    if platform.system() != "Linux":
        console.print("  [dim]Skipped (Linux only)[/dim]")
    else:
        hailo_ok, hailo_detail = _check_hailo_device()
        if not hailo_ok:
            all_ok = False
        _print_status("Hailo", hailo_ok, hailo_detail)

        camera_ok, camera_detail = _check_camera()
        if not camera_ok:
            all_ok = False
        _print_status("Camera", camera_ok, camera_detail)

        sensor_ok, sensor_detail = _check_sensor()
        if not sensor_ok:
            all_ok = False
        _print_status("Sensors", sensor_ok, sensor_detail)

    console.print()
    if all_ok:
        console.print("[green]All checks passed![/green]\n")
    else:
        console.print("[yellow]Some checks failed. Run subcommands for details:[/yellow]")
        console.print("  [cyan]bugcam status deps[/cyan]    - Software dependencies")
        console.print("  [cyan]bugcam status devices[/cyan] - Hardware connections")
        console.print("  [cyan]bugcam status models[/cyan]  - Installed models\n")

    raise typer.Exit(0 if all_ok else 1)
