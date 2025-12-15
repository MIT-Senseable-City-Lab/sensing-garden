from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

def print_success(message: str):
    console.print(f"[green]✓[/green] {message}")

def print_error(message: str):
    console.print(f"[red]✗[/red] {message}")

def print_info(message: str):
    console.print(f"[blue]ℹ[/blue] {message}")

def create_table(title: str, columns: list[str]) -> Table:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    return table
