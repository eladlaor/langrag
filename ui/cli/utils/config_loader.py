"""
Configuration file loading and merging.

Supports YAML and JSON config files with priority-based merging:
CLI flags (highest) > Environment variables > Config file (lowest)
"""

import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigLoader:
    """Load and merge YAML/JSON configurations with CLI arguments."""

    @staticmethod
    def load_config_file(file_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML or JSON file.

        Args:
            file_path: Path to config file (.yaml, .yml, or .json)

        Returns:
            Dictionary containing configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If file type is not supported
            yaml.YAMLError: If YAML parsing fails
            json.JSONDecodeError: If JSON parsing fails
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        try:
            with open(path, encoding="utf-8") as f:
                if path.suffix in [".yaml", ".yml"]:
                    config = yaml.safe_load(f)
                    return config if config is not None else {}
                elif path.suffix == ".json":
                    return json.load(f)
                else:
                    raise ValueError(f"Unsupported file type: {path.suffix}. Use .yaml, .yml, or .json")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file: {e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}") from e

    @staticmethod
    def merge_configs(
        config_file: Optional[Dict[str, Any]] = None,
        cli_args: Optional[Dict[str, Any]] = None,
        env_vars: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Merge configurations from multiple sources with priority.

        Priority order (highest to lowest):
        1. CLI arguments (--flags)
        2. Environment variables
        3. Config file

        Args:
            config_file: Configuration from file (lowest priority)
            cli_args: Configuration from CLI flags (highest priority)
            env_vars: Configuration from environment variables

        Returns:
            Merged configuration dictionary

        Example:
            >>> config = ConfigLoader.merge_configs(
            ...     config_file={"top_k_discussions": 5, "language": "hebrew"},
            ...     cli_args={"language": "english"}  # Overrides file
            ... )
            >>> config["language"]
            'english'
            >>> config["top_k_discussions"]
            5
        """
        merged: Dict[str, Any] = {}

        # Priority order: config_file (lowest) -> env_vars -> cli_args (highest)
        for source in [config_file, env_vars, cli_args]:
            if source:
                # Only override with non-None values
                for key, value in source.items():
                    if value is not None:
                        merged[key] = value

        return merged

    @staticmethod
    def validate_required_fields(config: Dict[str, Any], required_fields: list[str]) -> list[str]:
        """
        Check which required fields are missing from config.

        Args:
            config: Configuration dictionary
            required_fields: List of required field names

        Returns:
            List of missing field names (empty if all present)

        Example:
            >>> config = {"start_date": "2025-01-01"}
            >>> missing = ConfigLoader.validate_required_fields(
            ...     config, ["start_date", "end_date", "data_source_name"]
            ... )
            >>> missing
            ['end_date', 'data_source_name']
        """
        return [field for field in required_fields if not config.get(field)]
