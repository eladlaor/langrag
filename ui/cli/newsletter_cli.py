#!/usr/bin/env python3
"""
LangTalks Newsletter CLI - Main Entry Point

Command-line interface for generating newsletters from WhatsApp chats.
Provides interactive prompts, flag-based execution, and config file support.

Usage:
    langtalks generate periodic --config newsletter.yaml
    langtalks runs list
    langtalks batch status <job_id>
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import typer
from rich.console import Console

# Import command modules
from ui.cli.commands import generate

app = typer.Typer(
    name="langtalks",
    help="LangTalks Newsletter Generation CLI",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main():
    """
    LangTalks Newsletter CLI

    Generate automated newsletters from WhatsApp group chats.
    Supports interactive prompts, CLI flags, and YAML/JSON config files.
    """
    pass


# Register command groups
app.add_typer(generate.app, name="generate", help="Generate newsletters from WhatsApp chats")


if __name__ == "__main__":
    app()
