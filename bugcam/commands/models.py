"""Model bundle management for BugCam."""
from __future__ import annotations

import hashlib
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import DownloadColumn, Progress, TransferSpeedColumn
from rich.table import Table

from ..model_bundles import (
    BUNDLE_LABELS_FILENAME,
    BUNDLE_MODEL_FILENAME,
    LOCAL_BUNDLES_DIR,
    ModelBundle,
    get_bundle_dir,
    get_installed_bundles,
    get_models_cache_dir,
    get_remote_bundle_file_url,
    list_remote_bundle_names,
    resolve_bundle_reference,
)

app = typer.Typer(help="Manage detection model bundles")
console = Console()

MODELS_CACHE_DIR = get_models_cache_dir()


def list_available_models() -> list[str]:
    """List remote model bundle names."""
    return list_remote_bundle_names()


def check_remote_bundle_exists(model_name: str) -> bool:
    """Return True if both required files exist remotely."""
    for filename in (BUNDLE_MODEL_FILENAME, BUNDLE_LABELS_FILENAME):
        try:
            req = urllib.request.Request(get_remote_bundle_file_url(model_name, filename), method="HEAD")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            return False
    return True


def get_model_url(model_name: str) -> str:
    """Backwards-compatible alias returning the model.hef bundle URL."""
    return get_remote_bundle_file_url(model_name, BUNDLE_MODEL_FILENAME)


def get_model_size(model_name: str) -> Optional[int]:
    """Return the remote size of a bundle's model.hef file."""
    try:
        req = urllib.request.Request(get_model_url(model_name), method="HEAD")
        response = urllib.request.urlopen(req, timeout=10)
        content_length = response.headers.get("Content-Length")
        return int(content_length) if content_length else None
    except Exception:
        return None


def get_bundle_install_path(model_name: str) -> Path:
    """Return the bundle installation path in cache."""
    return get_bundle_dir(model_name, cache_dir=MODELS_CACHE_DIR)


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def calculate_checksum(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _download_file(url: str, destination: Path) -> None:
    with Progress(
        *Progress.get_default_columns(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        with urllib.request.urlopen(urllib.request.Request(url)) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            task = progress.add_task(f"[cyan]{destination.name}", total=total_size)
            with open(destination, "wb") as fh:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    fh.write(chunk)
                    progress.update(task, advance=len(chunk))


@app.command()
def download(
    model_name: Optional[str] = typer.Argument(None, help="Bundle to download (or 'all')"),
) -> None:
    """Download model bundles from cloud storage."""
    MODELS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    available_models = list_available_models()
    if not available_models:
        console.print("[red]Error: Could not fetch bundle list[/red]")
        console.print("[dim]Expected remote layout: <model>/model.hef and <model>/labels.txt[/dim]")
        raise typer.Exit(1)

    if model_name == "all":
        bundles_to_download = available_models.copy()
    elif model_name is None:
        console.print("[cyan]Available model bundles:[/cyan]\n")
        for name in available_models:
            size = get_model_size(name)
            size_str = format_size(size) if size else "?"
            console.print(f"  [bold]{name}[/bold]  ({size_str})")
        console.print("\n[dim]Usage:[/dim]")
        console.print("[dim]  bugcam models download <bundle-name>[/dim]")
        console.print("[dim]  bugcam models download all[/dim]")
        return
    else:
        if model_name not in available_models:
            console.print(f"[red]Unknown model bundle: {model_name}[/red]")
            console.print(f"Available bundles: {', '.join(available_models)}")
            raise typer.Exit(1)
        bundles_to_download = [model_name]

    downloaded = []
    skipped = []
    failed = []

    console.print(f"\n[cyan]Downloading {len(bundles_to_download)} bundle(s):[/cyan]")
    for bundle_name in bundles_to_download:
        install_path = get_bundle_install_path(bundle_name)
        status = "exists" if install_path.exists() else "pending"
        size = get_model_size(bundle_name)
        size_str = format_size(size) if size else "?"
        console.print(f"  {bundle_name:30} {size_str:>10}  [{status}]")
    console.print()

    for bundle_name in bundles_to_download:
        install_path = get_bundle_install_path(bundle_name)
        model_path = install_path / BUNDLE_MODEL_FILENAME
        labels_path = install_path / BUNDLE_LABELS_FILENAME
        if model_path.exists() and labels_path.exists():
            console.print(f"[yellow]Skipping {bundle_name} (already exists)[/yellow]")
            skipped.append(bundle_name)
            continue

        install_path.mkdir(parents=True, exist_ok=True)
        try:
            _download_file(get_remote_bundle_file_url(bundle_name, BUNDLE_MODEL_FILENAME), model_path)
            _download_file(get_remote_bundle_file_url(bundle_name, BUNDLE_LABELS_FILENAME), labels_path)
            console.print(f"[green]✓ Downloaded {bundle_name}[/green]")
            downloaded.append(bundle_name)
        except Exception as exc:
            console.print(f"[red]✗ Download failed for {bundle_name}: {exc}[/red]")
            shutil.rmtree(install_path, ignore_errors=True)
            failed.append(bundle_name)

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
    """List installed model bundles."""
    bundles = get_installed_bundles(require_labels=False, cache_dir=MODELS_CACHE_DIR, local_dir=LOCAL_BUNDLES_DIR)

    if not bundles:
        console.print("[yellow]No model bundles installed[/yellow]\n")
        console.print("[dim]Download a bundle with: bugcam models download <bundle-name>[/dim]")
        return

    table = Table(title="Installed Model Bundles")
    table.add_column("Bundle", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Labels", style="green")
    table.add_column("Modified", style="blue")
    table.add_column("Location", style="magenta")

    for bundle in bundles:
        model_status = "yes" if bundle.has_model else "no"
        labels_status = "yes" if bundle.has_labels else "no"
        modified_target = bundle.model_path if bundle.has_model else bundle.root
        modified = datetime.fromtimestamp(modified_target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(bundle.name, model_status, labels_status, modified, bundle.location)

    console.print(table)


@app.command()
def info(model_name: str) -> None:
    """Show details about a model bundle."""
    bundle = resolve_bundle_reference(
        model_name,
        require_labels=False,
        cache_dir=MODELS_CACHE_DIR,
        local_dir=LOCAL_BUNDLES_DIR,
    )

    if not bundle:
        console.print(f"[red]Model bundle '{model_name}' not found[/red]")
        console.print("Available bundles: " + ", ".join(b.name for b in get_installed_bundles(require_labels=False)))
        raise typer.Exit(1)

    table = Table(title=f"Model Bundle: {bundle.name}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Bundle Path", str(bundle.root))
    table.add_row("Location", bundle.location)
    table.add_row("model.hef", "present" if bundle.has_model else "missing")
    table.add_row("labels.txt", "present" if bundle.has_labels else "missing")

    if bundle.has_model:
        stats = bundle.model_path.stat()
        table.add_row("Model Size", format_size(stats.st_size))
        table.add_row("Model SHA256", calculate_checksum(bundle.model_path)[:16] + "...")
    if bundle.has_labels:
        label_count = len([line for line in bundle.labels_path.read_text(encoding="utf-8").splitlines() if line.strip()])
        table.add_row("Label Count", str(label_count))

    console.print(table)


@app.command()
def delete(model_name: Optional[str] = typer.Argument(None, help="Bundle to delete")) -> None:
    """Delete downloaded model bundles from cache."""
    bundles = get_installed_bundles(require_labels=False, cache_dir=MODELS_CACHE_DIR, local_dir=LOCAL_BUNDLES_DIR)
    if not bundles:
        console.print("[yellow]No model bundles installed[/yellow]")
        return

    if model_name is None:
        console.print("[cyan]Installed model bundles:[/cyan]\n")
        for bundle in bundles:
            suffix = "" if bundle.location == "cache" else " [dim](local - cannot delete)[/dim]"
            console.print(f"  {bundle.name}{suffix}")
        console.print("\n[dim]Usage:[/dim]")
        console.print("[dim]  bugcam models delete <bundle-name>[/dim]")
        return

    bundle = resolve_bundle_reference(
        model_name,
        require_labels=False,
        cache_dir=MODELS_CACHE_DIR,
        local_dir=LOCAL_BUNDLES_DIR,
    )
    if not bundle:
        console.print(f"[red]Model bundle '{model_name}' not found[/red]")
        raise typer.Exit(1)
    if bundle.location != "cache":
        console.print(f"[red]Cannot delete '{bundle.name}' from local resources[/red]")
        raise typer.Exit(1)

    if not typer.confirm(f"Delete model bundle {bundle.name}?"):
        console.print("[yellow]Deletion cancelled[/yellow]")
        return

    try:
        shutil.rmtree(bundle.root)
        console.print(f"[green]✓ Deleted {bundle.name}[/green]")
    except Exception as exc:
        console.print(f"[red]✗ Failed to delete: {exc}[/red]")
        raise typer.Exit(1)
