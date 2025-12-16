"""Device connection checker for bugcam."""
import typer
import subprocess
from pathlib import Path
from rich.console import Console

app = typer.Typer(help="Test device connections")
console = Console()


def check_camera() -> bool:
    """Test camera connection."""
    console.print("\n[bold cyan]Camera Check[/bold cyan]")

    try:
        # Try importing picamera2
        result = subprocess.run(
            ["/usr/bin/python3", "-c", "from picamera2 import Picamera2; Picamera2()"],
            capture_output=True,
            timeout=5
        )

        if result.returncode == 0:
            console.print("[green]✓ Camera accessible[/green]")
            return True

        # Check for specific numpy error
        stderr = result.stderr.decode()
        if "dtype size changed" in stderr or "ValueError" in stderr:
            console.print("[red]✗ Camera check failed - numpy binary incompatibility[/red]")
            console.print("[yellow]Fix: pip uninstall -y numpy && sudo apt install --reinstall python3-numpy python3-picamera2 python3-libcamera[/yellow]")
            return False

        console.print("[red]✗ Camera not accessible[/red]")
        if stderr:
            console.print(f"[dim]{stderr[:200]}[/dim]")
        return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ Camera check timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Camera check failed: {e}[/red]")
        return False


def check_sensor() -> bool:
    """Test air quality sensor connection."""
    console.print("\n[bold cyan]Sensor Check[/bold cyan]")

    # Check if I2C is enabled
    i2c_device = Path("/dev/i2c-1")
    if not i2c_device.exists():
        console.print("[red]✗ I2C not enabled (/dev/i2c-1 not found)[/red]")
        console.print("[yellow]Enable I2C using: sudo raspi-config[/yellow]")
        return False

    console.print("[green]✓ I2C enabled[/green]")

    # Try to detect sensors using i2cdetect
    try:
        result = subprocess.run(
            ["i2cdetect", "-y", "1"],
            capture_output=True,
            timeout=5
        )

        if result.returncode != 0:
            console.print("[yellow]! Could not scan I2C bus (i2cdetect not available)[/yellow]")
            return True

        output = result.stdout.decode()

        # Check for common sensor addresses
        sensors_found = []
        if "61" in output:
            sensors_found.append("SCD30 (0x61)")
        if "62" in output:
            sensors_found.append("SCD40/41 (0x62)")
        if "76" in output:
            sensors_found.append("BME280 (0x76)")
        if "77" in output:
            sensors_found.append("BME280 (0x77)")

        if sensors_found:
            console.print(f"[green]✓ Sensors detected: {', '.join(sensors_found)}[/green]")
            return True
        else:
            console.print("[yellow]! No known sensors detected on I2C bus[/yellow]")
            console.print("[dim]Looking for: SCD30 (0x61), SCD40 (0x62), BME280 (0x76/0x77)[/dim]")
            return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ Sensor check timed out[/red]")
        return False
    except FileNotFoundError:
        console.print("[yellow]! i2cdetect not found (install i2c-tools)[/yellow]")
        return True
    except Exception as e:
        console.print(f"[red]✗ Sensor check failed: {e}[/red]")
        return False


@app.command()
def camera() -> None:
    """Test camera connection."""
    success = check_camera()
    console.print()
    raise typer.Exit(0 if success else 1)


@app.command()
def sensor() -> None:
    """Test air quality sensor connection."""
    success = check_sensor()
    console.print()
    raise typer.Exit(0 if success else 1)


@app.command()
def all() -> None:
    """Run all device checks."""
    camera_ok = check_camera()
    sensor_ok = check_sensor()

    console.print()
    if camera_ok and sensor_ok:
        console.print("[green]All device checks passed![/green]")
        raise typer.Exit(0)
    else:
        console.print("[yellow]Some device checks failed[/yellow]")
        raise typer.Exit(1)
