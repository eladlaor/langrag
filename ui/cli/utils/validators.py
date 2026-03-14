"""
Interactive prompt helpers and validators.

Provides functions for validating input and prompting users for required fields.
"""

from datetime import datetime
from typing import List
from rich.prompt import Prompt
from rich.console import Console

from ui.cli.models.cli_types import DataSource, CHAT_NAMES


console = Console()


def validate_date(date_str: str) -> bool:
    """
    Validate date format (YYYY-MM-DD).

    Args:
        date_str: Date string to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_date("2025-01-01")
        True
        >>> validate_date("01/01/2025")
        False
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def prompt_chat_selection(data_source: DataSource) -> List[str]:
    """
    Prompt user to select chats for given data source.

    Args:
        data_source: DataSource enum value

    Returns:
        List of selected chat names

    Example:
        >>> selected = prompt_chat_selection(DataSource.LANGTALKS)
        Available chats:
          1. LangTalks Community
          2. LangTalks Community 2
          ...
        Select chats (comma-separated numbers, 'all', or press Enter for all):
        > 1,2
        Selected: ['LangTalks Community', 'LangTalks Community 2']
    """
    available_chats = CHAT_NAMES[data_source]

    console.print("\n[bold]Available chats:[/bold]")
    for i, chat in enumerate(available_chats, 1):
        console.print(f"  {i}. [cyan]{chat}[/cyan]")

    console.print(
        "\n[dim]Select chats (comma-separated numbers, 'all', or press Enter for all):[/dim]"
    )
    selection = Prompt.ask("Selection", default="all").strip()

    if not selection or selection.lower() == "all":
        console.print(f"[green]✅ Selected all {len(available_chats)} chats[/green]")
        return available_chats

    # Parse comma-separated indices
    try:
        indices = [int(x.strip()) for x in selection.split(",")]
        selected = [available_chats[i - 1] for i in indices if 1 <= i <= len(available_chats)]

        if not selected:
            console.print("[yellow]⚠️ Invalid selection, using all chats[/yellow]")
            return available_chats

        console.print(f"[green]✅ Selected {len(selected)} chat(s):[/green]")
        for chat in selected:
            console.print(f"  • [cyan]{chat}[/cyan]")

        return selected

    except (ValueError, IndexError):
        console.print("[yellow]⚠️ Invalid selection format, using all chats[/yellow]")
        return available_chats


def prompt_date_range() -> tuple[str, str]:
    """
    Prompt user for start and end dates with validation.

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format

    Example:
        >>> start, end = prompt_date_range()
        Start date (YYYY-MM-DD) [2025-01-01]: 2025-01-15
        End date (YYYY-MM-DD) [2025-12-19]: 2025-01-31
        ('2025-01-15', '2025-01-31')
    """
    # Suggest sensible defaults
    default_start = "2025-01-01"
    default_end = datetime.now().strftime("%Y-%m-%d")

    while True:
        start_date = Prompt.ask("Start date (YYYY-MM-DD)", default=default_start)
        if validate_date(start_date):
            break
        console.print("[red]❌ Invalid date format. Use YYYY-MM-DD[/red]")

    while True:
        end_date = Prompt.ask("End date (YYYY-MM-DD)", default=default_end)
        if validate_date(end_date):
            # Validate that end >= start
            if end_date >= start_date:
                break
            console.print("[red]❌ End date must be >= start date[/red]")
        else:
            console.print("[red]❌ Invalid date format. Use YYYY-MM-DD[/red]")

    return start_date, end_date


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """
    Prompt user for yes/no confirmation.

    Args:
        question: Question to ask
        default: Default value if user presses Enter

    Returns:
        True for yes, False for no

    Example:
        >>> result = prompt_yes_no("Enable consolidation?", default=True)
        Enable consolidation? [Y/n]: y
        True
    """
    from rich.prompt import Confirm

    return Confirm.ask(question, default=default)
