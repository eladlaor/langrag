#!/usr/bin/env python3
"""
One-time setup to configure and verify Beeper recovery code.

This script:
1. Validates your recovery code format
2. Tests connection to server-side backup
3. Saves BEEPER_RECOVERY_CODE to your .env file

Usage:
    python scripts/beeper_keys/setup_recovery_code.py

After setup, server backup keys will sync automatically on each newsletter run.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root and src to path for imports
# ui/cli/beeper_setup -> ui/cli -> ui -> langrag (project root)
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))  # For matrix_decryption
sys.path.insert(0, str(project_root / "src"))  # For src modules

from dotenv import load_dotenv, set_key


def main():
    """Main setup flow."""
    print("=" * 70)
    print("Beeper Recovery Code Setup")
    print("=" * 70)
    print()
    print("This script will configure automated server-side key backup sync.")
    print()
    print("What you need:")
    print("  - Your Beeper Recovery Code (from signup or settings)")
    print("  - BEEPER_ACCESS_TOKEN already set in .env")
    print()
    print("If you don't have your recovery code:")
    print("  1. Open Beeper app > Settings > Security & Privacy")
    print("  2. Look for 'Recovery Code' or 'Secure Storage'")
    print("  3. Or generate a new one (WARNING: loses old message access)")
    print()

    # Check for .env file
    env_path = project_root / ".env"
    if not env_path.exists():
        env_path = project_root / ".env.dev"
        if not env_path.exists():
            print("ERROR: No .env or .env.dev file found")
            print(f"       Expected at: {project_root / '.env'}")
            return 1

    load_dotenv(str(env_path))

    # Check for access token
    access_token = os.getenv("BEEPER_ACCESS_TOKEN")
    if not access_token:
        print("ERROR: BEEPER_ACCESS_TOKEN not set in .env")
        print("       Set this first before running this script")
        return 1

    print(f"Using .env file: {env_path}")
    print(f"Access token: {'*' * 20}...{access_token[-10:]}")
    print()

    # Get recovery code
    print("-" * 70)
    print("Enter your Beeper recovery code")
    print("(Spaces between groups are OK - they will be stripped)")
    print()
    recovery_code = input("Recovery Code: ").strip()

    if not recovery_code:
        print("ERROR: No recovery code provided")
        return 1

    print()
    print("-" * 70)
    print("Validating recovery code format...")

    # Import and validate
    try:
        from core.ingestion.decryption import RecoveryKeyDecoder, InvalidRecoveryCodeError
        decoder = RecoveryKeyDecoder()
        key = decoder.decode(recovery_code)
        print(f"  Valid: {len(key)}-byte key extracted")
    except InvalidRecoveryCodeError as e:
        print(f"  INVALID: {e}")
        print()
        print("Common issues:")
        print("  - Make sure you copied the entire code")
        print("  - Recovery code typically starts with 'E' followed by letters/numbers")
        print("  - Spaces between groups are OK")
        print("  - The code should be about 58 characters (without spaces)")
        return 1
    except ImportError as e:
        print(f"  WARNING: Could not import crypto module: {e}")
        print("  Skipping validation (will be validated on first use)")

    print()
    print("-" * 70)
    print("Testing server backup connection...")

    try:
        from core.ingestion.decryption import MatrixKeyBackupManager, BackupNotFoundError, JSONFileCacheAdapter
        from pathlib import Path

        async def test_connection():
            cache = JSONFileCacheAdapter(Path("./secrets/server_backup_keys.json"))
            manager = MatrixKeyBackupManager(
                homeserver="https://matrix.beeper.com",
                access_token=access_token,
                recovery_code=recovery_code,
                cache=cache,
            )
            version_info = await manager._fetch_backup_version()
            return version_info

        version_info = asyncio.run(test_connection())

        if version_info:
            print(f"  Connected: backup v{version_info.get('version', '?')}")
            print(f"  Key count: {version_info.get('count', 'unknown')}")
        else:
            print("  WARNING: No server-side backup found (404)")
            print("  This might mean:")
            print("    - Backup was never enabled in Beeper")
            print("    - Recovery code doesn't match current backup")
            print("  The recovery code will be saved anyway.")

    except BackupNotFoundError:
        print("  WARNING: No server-side backup found")
        print("  Enable backup in Beeper to use this feature")
    except Exception as e:
        print(f"  WARNING: Connection test failed: {e}")
        print("  The recovery code will be saved anyway.")
        print("  It will be tested again on the next newsletter run.")

    print()
    print("-" * 70)
    print("Saving to .env file...")

    # Format for storage (remove spaces)
    clean_code = recovery_code.replace(" ", "")

    try:
        set_key(str(env_path), "BEEPER_RECOVERY_CODE", clean_code)
        print(f"  Saved BEEPER_RECOVERY_CODE to {env_path}")
    except Exception as e:
        print(f"  ERROR: Could not save to .env: {e}")
        print()
        print("  Add this line manually to your .env file:")
        print(f"  BEEPER_RECOVERY_CODE={clean_code}")
        return 1

    print()
    print("=" * 70)
    print("Setup Complete!")
    print("=" * 70)
    print()
    print("What happens now:")
    print("  1. On each newsletter run, keys will sync from server backup")
    print("  2. Keys are cached locally in ./secrets/server_backup_keys.json")
    print("  3. Manual key export is no longer required!")
    print()
    print("To test:")
    print("  1. Rebuild Docker: docker compose build --no-cache")
    print("  2. Start Docker: docker compose up -d")
    print("  3. Run a newsletter generation")
    print("  4. Check logs for '✅ Synced X keys from server backup'")
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
