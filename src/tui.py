"""Rich TUI panels for pre-API-call confirmation and batch progress display."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(stderr=True)


def confirm_api_call(
    *,
    batch_label: str,
    provider: str,
    model_name: str,
    api_base_url: str = "",
    n_pages: int,
    total_pages: int,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: dict[str, Any] | float,
    estimated_time_seconds: float,
    reasoning_effort: str,
    batch_idx: int,
    total_batches: int,
    auto_confirm: bool = False,
) -> bool:
    """Display a rich TUI panel summarising the upcoming API call and ask for confirmation.

    Returns ``True`` if the user confirms (or ``auto_confirm`` is set), ``False`` otherwise.
    """
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Provider", provider.upper())
    table.add_row("Model", model_name)
    if api_base_url:
        table.add_row("Base URL", api_base_url)
    table.add_row("Reasoning", reasoning_effort or "none")
    table.add_row("Pages in batch", f"{n_pages}  (batch {batch_idx + 1}/{total_batches}, {total_pages} total)")
    table.add_row("Est. input tokens", f"{input_tokens:,}")
    table.add_row("Est. output tokens", f"{output_tokens:,}")
    cost_val = estimated_cost["total_cost_usd"] if isinstance(estimated_cost, dict) else estimated_cost
    table.add_row("Est. cost", f"${cost_val:.4f}")
    table.add_row("Est. time", f"~{estimated_time_seconds:.0f}s  (~{estimated_time_seconds / 60:.1f} min)")

    title = Text.assemble(
        ("  API Call  ", "bold white on blue"),
        ("  ", ""),
        (batch_label, "bold yellow"),
    )
    console.print()
    console.print(Panel(table, title=title, border_style="blue", padding=(1, 2)))

    if auto_confirm:
        console.print("[dim]Auto-confirmed (--yes flag)[/dim]")
        return True

    try:
        choice = console.input("[bold green]Proceed?[/bold green] \\[y]es / \\[s]kip batch / \\[q]uit: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if choice.startswith("y") or choice == "":
        return True
    if choice.startswith("q"):
        raise SystemExit(0)
    return False


def show_batch_summary(
    *,
    total_batches: int,
    total_pages: int,
    total_input_tokens: int,
    total_output_tokens: int,
    total_estimated_cost: float,
    total_estimated_time_seconds: float,
    provider: str,
    model_name: str,
    api_base_url: str = "",
    reasoning_effort: str,
) -> None:
    """Display an overview panel before the batch loop begins."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold magenta", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Provider", provider.upper())
    table.add_row("Model", model_name)
    if api_base_url:
        table.add_row("Base URL", api_base_url)
    table.add_row("Reasoning", reasoning_effort or "none")
    table.add_row("Total pages", str(total_pages))
    table.add_row("Batches", str(total_batches))
    table.add_row("Est. total input", f"{total_input_tokens:,} tokens")
    table.add_row("Est. total output", f"{total_output_tokens:,} tokens")
    table.add_row("Est. total cost", f"${total_estimated_cost:.4f}")
    table.add_row("Est. total time", f"~{total_estimated_time_seconds:.0f}s  (~{total_estimated_time_seconds / 60:.1f} min)")

    title = Text.assemble(("  Conversion Plan  ", "bold white on magenta"))
    console.print()
    console.print(Panel(table, title=title, border_style="magenta", padding=(1, 2)))
