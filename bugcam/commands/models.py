import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, DownloadColumn, TransferSpeedColumn
from datetime import datetime
import hashlib
import urllib.request
from typing import Optional

app = typer.Typer(help="Manage detection models")
console = Console()

# Models are cached in user's home directory
MODELS_CACHE_DIR = Path.home() / ".cache" / "bugcam" / "models"

# Also check local resources/ for development
LOCAL_RESOURCES_DIR = Path(__file__).parent.parent.parent / "resources"

# S3 bucket URL for models (public bucket)
MODELS_BASE_URL = "https://scl-sensing-garden-models.s3.amazonaws.com"

def list_s3_models() -> list[str]:
    """List available models from S3 bucket.

    Returns:
        List of model filenames (*.hef files).
    """
    try:
        # S3 bucket listing returns XML
        req = urllib.request.Request(MODELS_BASE_URL)
        response = urllib.request.urlopen(req, timeout=10)
        content = response.read().decode('utf-8')

        # Parse model names from XML (simple regex, avoids xml dependency)
        import re
        models = re.findall(r'<Key>([^<]+\.hef)</Key>', content)
        return sorted(models)
    except Exception:
        return []


def get_s3_model_size(model_name: str) -> Optional[int]:
    """Get model file size from S3 via HEAD request.

    Returns:
        Size in bytes, or None if request fails.
    """
    url = f"{MODELS_BASE_URL}/{model_name}"
    try:
        req = urllib.request.Request(url, method='HEAD')
        response = urllib.request.urlopen(req, timeout=5)
        content_length = response.headers.get('Content-Length')
        if content_length:
            return int(content_length)
    except Exception:
        pass
    return None


def get_models_dir() -> Path:
    """Get models directory, preferring cache, falling back to local."""
    if MODELS_CACHE_DIR.exists() and list(MODELS_CACHE_DIR.glob("*.hef")):
        return MODELS_CACHE_DIR
    if LOCAL_RESOURCES_DIR.exists() and list(LOCAL_RESOURCES_DIR.glob("*.hef")):
        return LOCAL_RESOURCES_DIR
    return MODELS_CACHE_DIR  # Default to cache dir


def get_hef_models() -> list[Path]:
    """Get all .hef model files, checking cache first, then local resources."""
    models = []

    # Check cache directory
    if MODELS_CACHE_DIR.exists():
        models.extend(MODELS_CACHE_DIR.glob("*.hef"))

    # Check local resources directory
    if LOCAL_RESOURCES_DIR.exists():
        for model in LOCAL_RESOURCES_DIR.glob("*.hef"):
            # Only add if not already found in cache
            if not any(m.name == model.name for m in models):
                models.append(model)

    return sorted(models)


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


@app.command()
def download(
    model_name: Optional[str] = typer.Argument(None, help="Model to download (or 'all')"),
) -> None:
    """Download detection models from cloud storage."""
    # Create cache dir if needed
    MODELS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Get available models from S3
    available_models = list_s3_models()
    if not available_models:
        console.print("[red]Error: Could not fetch model list from S3[/red]")
        console.print("[dim]Check your internet connection and try again.[/dim]")
        raise typer.Exit(1)

    # Determine which models to download
    if model_name == "all":
        models_to_download = available_models.copy()
    elif model_name is None:
        # Show available models from S3
        console.print("[cyan]Available models:[/cyan]\n")
        for name in available_models:
            size = get_s3_model_size(name)
            size_str = format_size(size) if size else "Unknown"
            console.print(f"  {name:20} {size_str:>10}")
        console.print("\n[dim]Usage:[/dim]")
        console.print("[dim]  bugcam models download <model_name>[/dim]")
        console.print("[dim]  bugcam models download all[/dim]")
        return
    else:
        # Add .hef extension if not present
        if not model_name.endswith('.hef'):
            model_name += '.hef'

        if model_name not in available_models:
            console.print(f"[red]Unknown model: {model_name}[/red]")
            console.print(f"Available models: {', '.join(available_models)}")
            raise typer.Exit(1)

        models_to_download = [model_name]

    # Show download summary
    console.print(f"\n[cyan]Downloading {len(models_to_download)} model(s):[/cyan]")
    for model in models_to_download:
        status = "exists" if (MODELS_CACHE_DIR / model).exists() else "pending"
        size = get_s3_model_size(model)
        size_str = format_size(size) if size else "Unknown"
        console.print(f"  {model:20} {size_str:>10}  [{status}]")
    console.print()

    # Track download results
    downloaded = []
    skipped = []
    failed = []

    # Download each model
    for model in models_to_download:
        dest_path = MODELS_CACHE_DIR / model
        url = f"{MODELS_BASE_URL}/{model}"

        # Skip if already exists
        if dest_path.exists():
            console.print(f"[yellow]Skipping {model} (already exists)[/yellow]")
            skipped.append(model)
            continue

        try:
            with Progress(
                *Progress.get_default_columns(),
                DownloadColumn(),
                TransferSpeedColumn(),
                console=console
            ) as progress:
                # Start download
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    task = progress.add_task(f"[cyan]{model}", total=total_size)

                    with open(dest_path, 'wb') as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            console.print(f"[green]✓ Downloaded {model}[/green]")
            downloaded.append(model)

        except urllib.error.HTTPError as e:
            console.print(f"[red]✗ HTTP Error {e.code}: {e.reason}[/red]")
            if dest_path.exists():
                dest_path.unlink()
            failed.append(model)
        except Exception as e:
            console.print(f"[red]✗ Download failed: {e}[/red]")
            if dest_path.exists():
                dest_path.unlink()
            failed.append(model)

    # Show summary
    if downloaded or skipped or failed:
        console.print("\n[cyan]Summary:[/cyan]")
        if downloaded:
            console.print(f"[green]  ✓ Downloaded: {len(downloaded)}[/green]")
        if skipped:
            console.print(f"[yellow]  - Skipped: {len(skipped)}[/yellow]")
        if failed:
            console.print(f"[red]  ✗ Failed: {len(failed)}[/red]")
            raise typer.Exit(1)


@app.command()
def list() -> None:
    """List available .hef models in cache and resources/ directories."""
    models = get_hef_models()

    if not models:
        console.print("[yellow]No models installed[/yellow]\n")
        console.print("[dim]Download a model with: bugcam models download <model_name>[/dim]")
        console.print("[dim]List available models: bugcam models download[/dim]")
        return

    table = Table(title="Installed Models")
    table.add_column("Filename", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Modified", style="blue")
    table.add_column("Location", style="magenta")

    for model in models:
        stats = model.stat()
        size = format_size(stats.st_size)
        modified = datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Determine location
        if MODELS_CACHE_DIR in model.parents:
            location = "cache"
        elif LOCAL_RESOURCES_DIR in model.parents:
            location = "local"
        else:
            location = "unknown"

        table.add_row(model.name, size, modified, location)

    console.print(table)


@app.command()
def info(model_name: str) -> None:
    """Show details about a specific model."""
    models = get_hef_models()

    # Find the model by name (with or without .hef extension)
    if not model_name.endswith('.hef'):
        model_name += '.hef'

    model_path = None
    for model in models:
        if model.name == model_name:
            model_path = model
            break

    if not model_path:
        console.print(f"[red]Model '{model_name}' not found[/red]")
        console.print(f"Available models: {', '.join(m.name for m in models)}")
        raise typer.Exit(1)

    stats = model_path.stat()
    checksum = calculate_checksum(model_path)

    table = Table(title=f"Model Info: {model_name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("File Path", str(model_path))
    table.add_row("Size", format_size(stats.st_size))
    table.add_row("Modified", datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("SHA256", checksum[:16] + "...")

    console.print(table)
