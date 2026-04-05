import typer
from rich.console import Console
from bugcam import __version__
from bugcam.commands import autostart, environment, heartbeat, models, process, record, run, setup, status, update, upload

app = typer.Typer(
    name="bugcam",
    help="CLI for Raspberry Pi insect detection with Hailo AI",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        print(f"bugcam {__version__}")
        raise typer.Exit()

# Register subcommand groups
app.add_typer(models.app, name="models")
app.add_typer(record.app, name="record")
app.add_typer(autostart.app, name="autostart")
app.add_typer(setup.app, name="setup")
app.add_typer(status.app, name="status")
app.add_typer(run.app, name="run")
app.add_typer(process.app, name="process")
app.add_typer(upload.app, name="upload")
app.add_typer(heartbeat.app, name="heartbeat")
app.add_typer(environment.app, name="environment")
app.add_typer(update.app, name="update")

@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the installed bugcam version and exit",
    ),
) -> None:
    """bugcam - Raspberry Pi insect detection CLI"""
    pass

if __name__ == "__main__":
    app()
