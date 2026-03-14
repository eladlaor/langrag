"""
Output formatters for CLI responses.

Provides functions to format API responses into readable terminal output
(tables, lists, JSON) to match frontend display capabilities.
"""

import json
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree


console = Console()


def format_periodic_newsletter_response(response: Dict[str, Any], json_mode: bool = False) -> None:
    """
    Format and display PeriodicNewsletterResponse.

    Args:
        response: API response dictionary
        json_mode: If True, output JSON instead of formatted display
    """
    if json_mode:
        console.print_json(data=response)
        return

    # Summary panel
    total = response.get("total_chats", 0)
    successful = response.get("successful_chats", 0)
    failed = response.get("failed_chats", 0)

    summary_text = f"[bold]Total Chats:[/bold] {total}  |  [green]✅ Success:[/green] {successful}  |  [red]❌ Failed:[/red] {failed}"
    console.print(Panel(summary_text, title="[bold cyan]Generation Summary[/bold cyan]", border_style="cyan"))

    # Per-chat results table
    if response.get("results"):
        _display_chat_results_table(response["results"])

    # Consolidation results
    if response.get("consolidated_newsletter"):
        _display_consolidation_results(response["consolidated_newsletter"])


def _display_chat_results_table(results: List[Dict[str, Any]]) -> None:
    """Display per-chat results in a table."""
    table = Table(title="Per-Chat Results", show_header=True, header_style="bold magenta")
    table.add_column("Chat Name", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Output Files")

    for result in results:
        chat_name = result.get("chat_name", "Unknown")
        success = result.get("success", False)
        status = "[green]✅ Success[/green]" if success else "[red]❌ Failed[/red]"

        if success:
            # Show available output files
            outputs = []
            if result.get("newsletter_md"):
                outputs.append(f"📄 MD: {_shorten_path(result['newsletter_md'])}")
            if result.get("newsletter_html"):
                outputs.append(f"🌐 HTML: {_shorten_path(result['newsletter_html'])}")
            if result.get("newsletter_json"):
                outputs.append(f"📋 JSON: {_shorten_path(result['newsletter_json'])}")
            output_text = "\n".join(outputs) if outputs else "-"
        else:
            error = result.get("error", "Unknown error")
            output_text = f"[red]{error}[/red]"

        table.add_row(chat_name, status, output_text)

    console.print("\n", table)


def _display_consolidation_results(consolidated: Dict[str, Any]) -> None:
    """Display consolidation results in a panel."""
    console.print("\n[bold magenta]🔀 Cross-Chat Consolidation Results[/bold magenta]")

    # Statistics
    stats = []
    if consolidated.get("total_chats_consolidated"):
        stats.append(f"[bold]Chats Consolidated:[/bold] {consolidated['total_chats_consolidated']}")
    if consolidated.get("total_discussions"):
        stats.append(f"[bold]Total Discussions:[/bold] {consolidated['total_discussions']}")
    if consolidated.get("total_messages_consolidated"):
        stats.append(f"[bold]Total Messages:[/bold] {consolidated['total_messages_consolidated']:,}")

    if stats:
        console.print(Panel(" | ".join(stats), border_style="magenta"))

    # Output files tree
    tree = Tree("📁 [bold]Consolidated Output Files[/bold]")

    if consolidated.get("md_path"):
        tree.add(f"📄 Markdown: [cyan]{_shorten_path(consolidated['md_path'])}[/cyan]")
    if consolidated.get("enriched_md_path"):
        tree.add(f"🔗 Enriched Markdown: [cyan]{_shorten_path(consolidated['enriched_md_path'])}[/cyan]")
    if consolidated.get("final_translated_path"):
        tree.add(f"🌐 Translated: [cyan]{_shorten_path(consolidated['final_translated_path'])}[/cyan]")
    if consolidated.get("json_path"):
        tree.add(f"📋 JSON: [cyan]{_shorten_path(consolidated['json_path'])}[/cyan]")
    if consolidated.get("discussions_ranking_path"):
        tree.add(f"⭐ Rankings: [cyan]{_shorten_path(consolidated['discussions_ranking_path'])}[/cyan]")

    # Per-chat outputs directory
    if consolidated.get("per_chat_outputs_dir"):
        tree.add(f"📂 Per-Chat Outputs: [dim]{_shorten_path(consolidated['per_chat_outputs_dir'])}[/dim]")

    console.print(tree)

    # Source chats
    if consolidated.get("source_chats"):
        chats_text = ", ".join([f"[cyan]{chat}[/cyan]" for chat in consolidated["source_chats"]])
        console.print(f"\n[dim]Sources: {chats_text}[/dim]")


def format_runs_list(runs: List[Dict[str, Any]], total: int) -> None:
    """
    Format and display runs list.

    Args:
        runs: List of run dictionaries
        total: Total number of runs available
    """
    table = Table(title=f"Newsletter Runs ({len(runs)} of {total})", show_header=True, header_style="bold cyan")
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Data Source", style="magenta")
    table.add_column("Date Range")
    table.add_column("Created", style="dim")
    table.add_column("Status", justify="center")

    for run in runs:
        run_id = run.get("run_id", "Unknown")
        data_source = run.get("data_source", "-")
        start = run.get("start_date", "")
        end = run.get("end_date", "")
        date_range = f"{start} → {end}" if start and end else "-"
        created = run.get("created_at", "-")

        # Status indicators
        status_parts = []
        if run.get("has_consolidated"):
            status_parts.append("[green]📦 Consolidated[/green]")
        if run.get("has_per_chat"):
            status_parts.append("[blue]📁 Per-Chat[/blue]")
        if run.get("has_hitl_pending"):
            status_parts.append("[yellow]⏳ HITL Pending[/yellow]")

        status = " ".join(status_parts) if status_parts else "[dim]No outputs[/dim]"

        table.add_row(run_id, data_source, date_range, created, status)

    console.print("\n", table)


def format_batch_jobs(jobs: List[Dict[str, Any]], total: int) -> None:
    """
    Format and display batch jobs list.

    Args:
        jobs: List of batch job dictionaries
        total: Total number of jobs available
    """
    table = Table(title=f"Batch Jobs ({len(jobs)} of {total})", show_header=True, header_style="bold yellow")
    table.add_column("Job ID", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Data Source", style="magenta")
    table.add_column("Date Range")
    table.add_column("Created", style="dim")

    for job in jobs:
        job_id = job.get("job_id", "Unknown")[:8]  # Shorten UUID
        status = job.get("status", "unknown")
        data_source = job.get("data_source_name", "-")
        start = job.get("start_date", "")
        end = job.get("end_date", "")
        date_range = f"{start} → {end}" if start and end else "-"
        created = job.get("created_at", "-")

        # Status styling
        status_styled = _format_batch_status(status)

        table.add_row(job_id, status_styled, data_source, date_range, created)

    console.print("\n", table)


def format_batch_job_status(job: Dict[str, Any]) -> None:
    """
    Format and display detailed batch job status.

    Args:
        job: Batch job status dictionary
    """
    job_id = job.get("job_id", "Unknown")
    status = job.get("status", "unknown")

    # Status panel
    status_styled = _format_batch_status(status)
    console.print(Panel(
        f"[bold]Job ID:[/bold] {job_id}\n[bold]Status:[/bold] {status_styled}",
        title="[bold yellow]Batch Job Status[/bold yellow]",
        border_style="yellow"
    ))

    # Timestamps
    timestamps = []
    if job.get("created_at"):
        timestamps.append(f"[bold]Created:[/bold] {job['created_at']}")
    if job.get("started_at"):
        timestamps.append(f"[bold]Started:[/bold] {job['started_at']}")
    if job.get("completed_at"):
        timestamps.append(f"[bold]Completed:[/bold] {job['completed_at']}")

    if timestamps:
        console.print("\n" + " | ".join(timestamps))

    # Request details
    console.print("\n[bold]Request Details:[/bold]")
    details = []
    if job.get("data_source_name"):
        details.append(f"  Data Source: [cyan]{job['data_source_name']}[/cyan]")
    if job.get("start_date"):
        details.append(f"  Date Range: {job['start_date']} → {job['end_date']}")
    if details:
        console.print("\n".join(details))

    # Output or error
    if status == "completed" and job.get("output_dir"):
        console.print(f"\n[green]✅ Output Directory:[/green] [cyan]{job['output_dir']}[/cyan]")
    elif status == "failed" and job.get("error_message"):
        console.print(f"\n[red]❌ Error:[/red] {job['error_message']}")


def format_newsletter_content(content: Dict[str, Any], format_type: str = "html") -> None:
    """
    Format and display newsletter content.

    Args:
        content: Newsletter content dictionary
        format_type: Content format (html, md, json)
    """
    run_id = content.get("run_id", "Unknown")
    title = content.get("title", "Newsletter")

    console.print(Panel(
        f"[bold]Run:[/bold] {run_id}\n[bold]Title:[/bold] {title}",
        title=f"[bold green]Newsletter ({format_type.upper()})[/bold green]",
        border_style="green"
    ))

    # Display content based on format
    if format_type == "html" and content.get("content_html"):
        # Show HTML with syntax highlighting (first 50 lines)
        html_lines = content["content_html"].split("\n")[:50]
        syntax = Syntax("\n".join(html_lines), "html", theme="monokai", line_numbers=True)
        console.print("\n", syntax)
        if len(content["content_html"].split("\n")) > 50:
            console.print("\n[dim]... (truncated, use --json for full content)[/dim]")

    elif format_type == "md" and content.get("content_md"):
        # Show Markdown
        console.print("\n", Panel(content["content_md"], border_style="green"))

    elif format_type == "json":
        # Show JSON
        console.print_json(data=content)

    # File path
    if content.get("file_path"):
        console.print(f"\n[dim]File: {content['file_path']}[/dim]")


def format_discussion_selection(discussions: List[Dict[str, Any]], total: int, deadline: Optional[str] = None) -> None:
    """
    Format and display discussions for HITL selection.

    Args:
        discussions: List of ranked discussion dictionaries
        total: Total number of discussions
        deadline: ISO timestamp for selection deadline
    """
    console.print(Panel(
        f"[bold]Total Discussions:[/bold] {total}\n" +
        (f"[bold]Selection Deadline:[/bold] [yellow]{deadline}[/yellow]" if deadline else ""),
        title="[bold cyan]📝 Discussion Selection[/bold cyan]",
        border_style="cyan"
    ))

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Rank", justify="right", style="cyan", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Group", style="dim")
    table.add_column("Score", justify="center", width=8)
    table.add_column("Messages", justify="center", width=10)
    table.add_column("Summary")

    for disc in discussions:
        rank = str(disc.get("rank", "?"))
        title = disc.get("title", "Untitled")
        group = disc.get("group_name", "-")
        score = f"{disc.get('relevance_score', 0):.1f}"
        num_messages = str(disc.get("num_messages", 0))
        nutshell = disc.get("nutshell", "")[:80]  # Truncate long summaries

        # Color code by score
        if disc.get("relevance_score", 0) >= 9:
            score_styled = f"[green]{score}[/green]"
        elif disc.get("relevance_score", 0) >= 7:
            score_styled = f"[yellow]{score}[/yellow]"
        else:
            score_styled = f"[dim]{score}[/dim]"

        table.add_row(rank, title, group, score_styled, num_messages, nutshell)

    console.print("\n", table)


def _format_batch_status(status: str) -> str:
    """Format batch job status with colors and emojis."""
    status_map = {
        "queued": "[yellow]⏳ Queued[/yellow]",
        "processing": "[blue]⚙️ Processing[/blue]",
        "completed": "[green]✅ Completed[/green]",
        "failed": "[red]❌ Failed[/red]",
        "cancelled": "[dim]🚫 Cancelled[/dim]",
    }
    return status_map.get(status, f"[dim]{status}[/dim]")


def _shorten_path(path: str, max_length: int = 60) -> str:
    """Shorten file path for display."""
    if not path:
        return "-"
    if len(path) <= max_length:
        return path

    # Show start and end of path
    prefix_len = max_length // 2 - 2
    suffix_len = max_length - prefix_len - 3
    return f"{path[:prefix_len]}...{path[-suffix_len:]}"


def print_error(message: str) -> None:
    """Print error message in consistent format."""
    console.print(f"\n[red bold]❌ Error:[/red bold] {message}\n")


def print_success(message: str) -> None:
    """Print success message in consistent format."""
    console.print(f"\n[green bold]✅ {message}[/green bold]\n")


def print_warning(message: str) -> None:
    """Print warning message in consistent format."""
    console.print(f"\n[yellow bold]⚠️ Warning:[/yellow bold] {message}\n")


def print_info(message: str) -> None:
    """Print info message in consistent format."""
    console.print(f"\n[blue]ℹ️ {message}[/blue]\n")
