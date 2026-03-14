"""
Rich progress tracking for SSE events.

Maps Server-Sent Events (SSE) from the streaming API to Rich progress bars,
spinners, and tables for a beautiful terminal UI.
"""

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from typing import Dict, List, Optional


class ProgressTracker:
    """Track workflow progress from SSE events with Rich UI."""

    def __init__(self, console: Console):
        """
        Initialize progress tracker.

        Args:
            console: Rich Console instance for output
        """
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        self.overall_task: Optional[int] = None
        self.chat_tasks: Dict[str, int] = {}
        self.results: List[Dict[str, str]] = []
        self.started = False

    def handle_event(self, event: Dict[str, any]):
        """
        Process SSE event and update progress displays.

        Args:
            event: SSE event dictionary with event_type and data
        """
        event_type = event.get("event_type")
        data = event.get("data", {})

        # Route event to appropriate handler
        handlers = {
            "workflow_started": self._on_workflow_started,
            "chat_started": self._on_chat_started,
            "stage_progress": self._on_stage_progress,
            "chat_completed": self._on_chat_completed,
            "chat_failed": self._on_chat_failed,
            "consolidation_started": self._on_consolidation_started,
            "consolidation_completed": self._on_consolidation_completed,
            "workflow_completed": self._on_workflow_completed,
            "error": self._on_error,
        }

        handler = handlers.get(event_type)
        if handler:
            handler(data)

    def _on_workflow_started(self, data: Dict[str, any]):
        """Handle workflow_started event - create overall progress bar."""
        if not self.started:
            self.progress.start()
            self.started = True

        total_chats = data.get("total_chats", 0)
        self.overall_task = self.progress.add_task(
            "[bold blue]Overall Progress[/bold blue]",
            total=total_chats,
        )

    def _on_chat_started(self, data: Dict[str, any]):
        """Handle chat_started event - create chat-specific progress bar."""
        chat_name = data.get("chat_name", "Unknown")
        task_id = self.progress.add_task(
            f"[cyan]{chat_name}[/cyan]",
            total=8,  # 8 stages per chat
        )
        self.chat_tasks[chat_name] = task_id

    def _on_stage_progress(self, data: Dict[str, any]):
        """Handle stage_progress event - update chat progress and stage label."""
        chat_name = data.get("chat_name")
        stage = data.get("stage")
        status = data.get("status")

        if chat_name not in self.chat_tasks:
            return

        task_id = self.chat_tasks[chat_name]

        # Update progress bar
        if status == "completed":
            self.progress.update(task_id, advance=1)

        # Update description with current stage and emoji
        stage_emoji = {
            "extract_messages": "📥",
            "preprocess_messages": "🔧",
            "translate_messages": "🌍",
            "separate_discussions": "✂️",
            "rank_discussions": "⭐",
            "generate_newsletter": "✍️",
            "enrich_with_links": "🔗",
            "translate_final": "🌐",
        }
        emoji = stage_emoji.get(stage, "⚙️")
        stage_label = stage.replace("_", " ").title()
        self.progress.update(task_id, description=f"[cyan]{chat_name}[/cyan] {emoji} {stage_label}")

    def _on_chat_completed(self, data: Dict[str, any]):
        """Handle chat_completed event - mark chat as done."""
        chat_name = data.get("chat_name")

        if chat_name in self.chat_tasks:
            task_id = self.chat_tasks[chat_name]
            self.progress.update(
                task_id,
                completed=8,
                description=f"[green]✅ {chat_name}[/green]",
            )

        if self.overall_task is not None:
            self.progress.update(self.overall_task, advance=1)

        self.results.append({"chat": chat_name, "status": "success"})

    def _on_chat_failed(self, data: Dict[str, any]):
        """Handle chat_failed event - mark chat as failed with error."""
        chat_name = data.get("chat_name")
        error = data.get("error", "Unknown error")

        if chat_name in self.chat_tasks:
            task_id = self.chat_tasks[chat_name]
            self.progress.update(
                task_id,
                description=f"[red]❌ {chat_name}: {error}[/red]",
            )

        if self.overall_task is not None:
            self.progress.update(self.overall_task, advance=1)

        self.results.append({"chat": chat_name, "status": "failed", "error": error})

    def _on_consolidation_started(self, data: Dict[str, any]):
        """Handle consolidation_started event - show consolidation message."""
        self.console.print("\n[bold magenta]🔀 Starting cross-chat consolidation...[/bold magenta]")

    def _on_consolidation_completed(self, data: Dict[str, any]):
        """Handle consolidation_completed event - show completion message."""
        self.console.print("[green]✅ Consolidation completed[/green]")

        # Extract consolidation details if available
        if "consolidated_newsletter" in data:
            consolidated = data["consolidated_newsletter"]
            total_discussions = consolidated.get("total_discussions", 0)
            total_chats = consolidated.get("total_chats_consolidated", 0)
            self.console.print(
                f"[dim]Consolidated {total_discussions} discussions from {total_chats} chats[/dim]"
            )

    def _on_workflow_completed(self, data: Dict[str, any]):
        """Handle workflow_completed event - stop progress and show summary."""
        if self.started:
            self.progress.stop()

    def _on_error(self, data: Dict[str, any]):
        """Handle error event - display error message."""
        message = data.get("message", "Unknown error occurred")
        self.console.print(f"[red bold]❌ Error: {message}[/red bold]")

    def show_summary(self):
        """Display final results summary table."""
        if not self.results:
            return

        table = Table(title="Newsletter Generation Results")
        table.add_column("Chat", style="cyan", no_wrap=True)
        table.add_column("Status", style="bold")
        table.add_column("Details")

        for result in self.results:
            chat = result["chat"]
            status = "✅ Success" if result["status"] == "success" else "❌ Failed"
            status_style = "green" if result["status"] == "success" else "red"
            details = result.get("error", "-")

            table.add_row(
                chat,
                f"[{status_style}]{status}[/{status_style}]",
                details,
            )

        self.console.print("\n", table)
