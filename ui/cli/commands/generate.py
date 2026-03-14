"""
Newsletter generation commands.

Handles periodic newsletter generation with support for:
- Interactive prompts
- CLI flags
- Config files (YAML/JSON)
- Real-time progress tracking
- Batch mode
"""

import json
import typer
import httpx
from datetime import datetime
from rich.console import Console
from rich.prompt import Prompt
from typing import Optional, List

from ui.cli.utils.api_client import NewsletterAPIClient
from ui.cli.utils.config_loader import ConfigLoader
from ui.cli.utils.progress import ProgressTracker
from ui.cli.utils.validators import prompt_chat_selection, prompt_date_range, prompt_yes_no
from ui.cli.utils import formatters
from ui.cli.models.cli_types import (
    DataSource,
    Language,
    SummaryFormat,
    SimilarityThreshold,
    OutputAction,
    CHAT_NAMES,
)


app = typer.Typer(help="Generate newsletters from WhatsApp chats")
console = Console()


@app.command()
def periodic(
    # Required (if not in config)
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Start date in YYYY-MM-DD format",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="End date in YYYY-MM-DD format",
    ),
    data_source: Optional[DataSource] = typer.Option(
        None,
        "--data-source",
        help="Data source (langtalks, mcp_israel, n8n_israel)",
    ),
    chats: Optional[List[str]] = typer.Option(
        None,
        "--chats",
        help="Chat names to include (can specify multiple times)",
    ),
    language: Optional[Language] = typer.Option(
        None,
        "--language",
        help="Target language for newsletter",
    ),
    summary_format: Optional[SummaryFormat] = typer.Option(
        None,
        "--format",
        help="Newsletter format template",
    ),
    # Config file
    config: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to YAML/JSON config file",
    ),
    # Force refresh flags
    force_all: bool = typer.Option(
        False,
        "--force-all",
        help="Force refresh all pipeline stages",
    ),
    force_extraction: bool = typer.Option(
        False,
        "--force-extraction",
        help="Force re-extraction of messages",
    ),
    force_preprocessing: bool = typer.Option(
        False,
        "--force-preprocessing",
        help="Force re-preprocessing of messages",
    ),
    force_translation: bool = typer.Option(
        False,
        "--force-translation",
        help="Force re-translation of messages",
    ),
    force_discussions: bool = typer.Option(
        False,
        "--force-discussions",
        help="Force re-separation of discussions",
    ),
    force_content: bool = typer.Option(
        False,
        "--force-content",
        help="Force re-generation of newsletter content",
    ),
    force_final_translation: bool = typer.Option(
        False,
        "--force-final-translation",
        help="Force re-translation of final summary",
    ),
    # Consolidation
    consolidate: bool = typer.Option(
        True,
        "--consolidate",
        help="Enable cross-chat consolidation",
    ),
    no_consolidate: bool = typer.Option(
        False,
        "--no-consolidate",
        help="Disable cross-chat consolidation",
    ),
    # Content configuration
    top_k: int = typer.Option(
        5,
        "--top-k",
        help="Number of featured discussions (1-20)",
        min=1,
        max=20,
    ),
    previous_newsletters: int = typer.Option(
        5,
        "--previous-newsletters",
        help="Number of previous newsletters for anti-repetition (0-20)",
        min=0,
        max=20,
    ),
    enable_merging: bool = typer.Option(
        True,
        "--enable-merging/--no-merging",
        help="Enable discussion merging across chats",
    ),
    similarity: SimilarityThreshold = typer.Option(
        SimilarityThreshold.MODERATE,
        "--similarity",
        help="Discussion merging threshold (strict/moderate/aggressive)",
    ),
    # HITL
    hitl_timeout: int = typer.Option(
        0,
        "--hitl-timeout",
        help="HITL timeout in minutes (0=disabled)",
        min=0,
    ),
    # LinkedIn
    linkedin: bool = typer.Option(
        False,
        "--linkedin",
        help="Create LinkedIn draft post",
    ),
    # Batch mode
    batch: bool = typer.Option(
        False,
        "--batch",
        help="Use OpenAI Batch API (50%% cost savings, async)",
    ),
    # Output
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        help="Override default output directory",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="JSON output format (for scripting)",
    ),
    # Non-interactive mode
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Non-interactive mode (fail if required fields missing)",
    ),
    # API base URL
    api_url: str = typer.Option(
        "http://localhost:8000",
        "--api-url",
        help="FastAPI backend URL",
        envvar="LANGTALKS_API_URL",
    ),
):
    """
    Generate periodic newsletter from WhatsApp chats.

    Supports three modes:

    \b
    1. Interactive: Prompts for missing required fields
       $ langtalks generate periodic

    \b
    2. Non-interactive: All parameters via flags
       $ langtalks generate periodic --start-date 2025-01-01 --end-date 2025-01-15 \\
         --data-source langtalks --chats "LangTalks Community" --language english

    \b
    3. Config file: Load from YAML/JSON (flags override config)
       $ langtalks generate periodic --config newsletter.yaml --force-all

    Examples:

    \b
      # Interactive mode with guided prompts
      $ langtalks generate periodic

      # Generate with config file
      $ langtalks generate periodic --config newsletter.yaml

      # Override config with specific dates
      $ langtalks generate periodic --config newsletter.yaml \\
        --start-date 2025-02-01 --end-date 2025-02-15

      # Batch mode for cost optimization
      $ langtalks generate periodic --config newsletter.yaml --batch

      # Force refresh all stages
      $ langtalks generate periodic --config newsletter.yaml --force-all
    """
    try:
        # 1. Load config file (if provided)
        config_data = {}
        if config:
            try:
                config_data = ConfigLoader.load_config_file(config)
                formatters.print_info(f"Loaded config from: {config}")
            except (FileNotFoundError, ValueError) as e:
                formatters.print_error(f"Config file error: {e}")
                raise typer.Exit(1)

        # 2. Build CLI args dict (only non-None/non-default values)
        cli_args = {}

        # Required fields
        if start_date:
            cli_args["start_date"] = start_date
        if end_date:
            cli_args["end_date"] = end_date
        if data_source:
            cli_args["data_source_name"] = data_source.value
        if chats:
            cli_args["whatsapp_chat_names_to_include"] = chats
        if language:
            cli_args["desired_language_for_summary"] = language.value
        if summary_format:
            cli_args["summary_format"] = summary_format.value

        # Optional fields (only if non-default)
        if output_dir:
            cli_args["output_dir"] = output_dir
        if no_consolidate:  # Only if explicitly disabled
            cli_args["consolidate_chats"] = False
        elif consolidate != True:  # Only if explicitly set to False (not default)
            cli_args["consolidate_chats"] = consolidate
        if top_k != 5:
            cli_args["top_k_discussions"] = top_k
        if previous_newsletters != 5:
            cli_args["previous_newsletters_to_consider"] = previous_newsletters
        if not enable_merging:  # Only if explicitly disabled
            cli_args["enable_discussion_merging"] = False
        if similarity != SimilarityThreshold.MODERATE:
            cli_args["similarity_threshold"] = similarity.value
        if hitl_timeout > 0:
            cli_args["hitl_selection_timeout_minutes"] = hitl_timeout
        if linkedin:
            cli_args["create_linkedin_draft"] = True
        if batch:
            cli_args["use_batch_api"] = True

        # Force refresh flags
        if force_all:
            cli_args.update(
                {
                    "force_refresh_extraction": True,
                    "force_refresh_preprocessing": True,
                    "force_refresh_translation": True,
                    "force_refresh_separate_discussions": True,
                    "force_refresh_content": True,
                    "force_refresh_final_translation": True,
                }
            )
        else:
            if force_extraction:
                cli_args["force_refresh_extraction"] = True
            if force_preprocessing:
                cli_args["force_refresh_preprocessing"] = True
            if force_translation:
                cli_args["force_refresh_translation"] = True
            if force_discussions:
                cli_args["force_refresh_separate_discussions"] = True
            if force_content:
                cli_args["force_refresh_content"] = True
            if force_final_translation:
                cli_args["force_refresh_final_translation"] = True

        # 3. Merge configs (CLI > Config File)
        merged = ConfigLoader.merge_configs(config_file=config_data, cli_args=cli_args)

        # 4. Interactive prompts for missing required fields
        if not non_interactive:
            merged = _prompt_for_required_fields(merged)

        # 5. Validate required fields are present
        required_fields = [
            "start_date",
            "end_date",
            "data_source_name",
            "whatsapp_chat_names_to_include",
            "desired_language_for_summary",
            "summary_format",
        ]
        missing = ConfigLoader.validate_required_fields(merged, required_fields)

        if missing:
            formatters.print_error(f"Missing required fields: {', '.join(missing)}")
            formatters.print_warning("Use interactive mode (remove --non-interactive) or provide via --config")
            raise typer.Exit(1)

        # 6. Execute generation
        with NewsletterAPIClient(base_url=api_url) as client:
            if json_output:
                # Non-streaming mode for JSON output
                console.print("[dim]Generating newsletter (non-streaming)...[/dim]")
                result = client.generate_periodic_newsletter(merged, stream=False)
                console.print(json.dumps(result, indent=2))
            else:
                # Streaming mode with Rich progress
                console.print("[bold]🚀 Starting newsletter generation...[/bold]\n")
                tracker = ProgressTracker(console)

                # Store final result from last event
                final_result = None
                for event in client.generate_periodic_newsletter(merged, stream=True):
                    tracker.handle_event(event)
                    # Capture final result from workflow_completed event
                    if event.get("event_type") == "workflow_completed":
                        final_result = event.get("data", {}).get("result")

                # Display formatted results
                if final_result:
                    console.print("\n")
                    formatters.format_periodic_newsletter_response(final_result)
                else:
                    # Fallback to basic summary if no final result
                    tracker.show_summary()

        formatters.print_success("Newsletter generation completed successfully!")

    except httpx.HTTPStatusError as e:
        formatters.print_error(f"API Error: {e.response.status_code}\n{e.response.text}")
        raise typer.Exit(1)
    except httpx.ConnectError:
        formatters.print_error(f"Connection Error: Could not connect to API at {api_url}")
        formatters.print_warning("Ensure the FastAPI backend is running (docker compose up)")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        formatters.print_warning("Interrupted by user")
        raise typer.Exit(130)
    except Exception as e:
        formatters.print_error(f"Unexpected error: {e}")
        if not json_output:
            import traceback

            traceback.print_exc()
        raise typer.Exit(1)


def _prompt_for_required_fields(config: dict) -> dict:
    """
    Prompt for missing required fields interactively.

    Args:
        config: Current configuration dictionary

    Returns:
        Updated configuration with prompted values
    """
    console.print("\n[bold cyan]📝 Newsletter Configuration[/bold cyan]\n")

    # Date range
    if not config.get("start_date") or not config.get("end_date"):
        from ui.cli.utils.validators import prompt_date_range

        start, end = prompt_date_range()
        config["start_date"] = start
        config["end_date"] = end

    # Data source
    if not config.get("data_source_name"):
        data_source = Prompt.ask(
            "\nData source",
            choices=["langtalks", "mcp_israel", "n8n_israel"],
            default="langtalks",
        )
        config["data_source_name"] = data_source

    # Chats (multi-select)
    if not config.get("whatsapp_chat_names_to_include"):
        selected_chats = prompt_chat_selection(DataSource(config["data_source_name"]))
        config["whatsapp_chat_names_to_include"] = selected_chats

    # Language
    if not config.get("desired_language_for_summary"):
        language = Prompt.ask(
            "\nTarget language",
            choices=["english", "hebrew", "spanish", "french"],
            default="english",
        )
        config["desired_language_for_summary"] = language

    # Format
    if not config.get("summary_format"):
        format_choice = Prompt.ask(
            "Newsletter format",
            choices=["langtalks_format", "mcp_israel_format"],
            default="langtalks_format",
        )
        config["summary_format"] = format_choice

    console.print("\n[green]✅ Configuration complete![/green]\n")

    return config
