import typer
from rich.console import Console
from bugcam.commands import models, detect, preview, autostart

app = typer.Typer(
    name="bugcam",
    help="CLI for Raspberry Pi insect detection with Hailo AI",
    add_completion=False,
)
console = Console()

# Register subcommand groups
app.add_typer(models.app, name="models")
app.add_typer(detect.app, name="detect")
app.add_typer(preview.app, name="preview")
app.add_typer(autostart.app, name="autostart")

@app.callback()
def main():
    """bugcam - Raspberry Pi insect detection CLI"""
    pass

if __name__ == "__main__":
    app()
