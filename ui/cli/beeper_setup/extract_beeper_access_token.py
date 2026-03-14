#!/usr/bin/env python3
"""
Extract BEEPER_ACCESS_TOKEN from Beeper Desktop's local database

This script safely extracts your Matrix access token from Beeper's SQLite database
and provides instructions for adding it to your .env file.

SECURITY NOTE: Your access token is sensitive. Never commit it to git!
"""

import os
import sqlite3
import sys
from pathlib import Path


def extract_beeper_access_token():
    """Extract access token from Beeper Desktop database"""

    print("🔑 Beeper Access Token Extractor")
    print("=" * 70)
    print()

    # Locate Beeper database
    beeper_db = Path.home() / '.config' / 'BeeperTexts' / 'account.db'

    if not beeper_db.exists():
        print(f"❌ Beeper database not found at: {beeper_db}")
        print()
        print("Please ensure:")
        print("  1. Beeper Desktop is installed")
        print("  2. You're logged in to Beeper")
        print("  3. The path is correct for your system")
        return False

    print(f"📂 Found Beeper database: {beeper_db}")
    print()

    # Extract access token
    try:
        conn = sqlite3.connect(f"file:{beeper_db}?mode=ro", uri=True)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, device_id, access_token, homeserver
            FROM account
            LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if not row:
            print("❌ No account found in database")
            print("   Please log in to Beeper Desktop first")
            return False

        user_id, device_id, access_token, homeserver = row

        print("✅ Account Information:")
        print(f"   User ID: {user_id}")
        print(f"   Device ID: {device_id}")
        print(f"   Homeserver: {homeserver}")
        print(f"   Access Token: {'*' * 20}...{access_token[-10:]}")
        print(f"   Token Length: {len(access_token)} characters")
        print()

        # Check if .env exists
        env_file = Path(".env")
        env_example = Path(".env.example")

        print("=" * 70)
        print("📝 Setup Instructions")
        print("=" * 70)
        print()

        if not env_file.exists():
            print("⚠️  .env file not found")
            if env_example.exists():
                print(f"   Copying {env_example} to {env_file}...")
                env_file.write_text(env_example.read_text())
                print("   ✓ Created .env from .env.example")
            else:
                print("   Creating new .env file...")
                env_file.write_text("# Beeper Configuration\n")
                print("   ✓ Created new .env file")
            print()

        # Add to .env
        env_content = env_file.read_text()

        if "BEEPER_ACCESS_TOKEN" in env_content:
            print("⚠️  BEEPER_ACCESS_TOKEN already exists in .env")
            print("   Updating with new value...")

            # Replace existing value
            lines = env_content.split('\n')
            updated_lines = []
            for line in lines:
                if line.startswith("BEEPER_ACCESS_TOKEN="):
                    updated_lines.append(f"BEEPER_ACCESS_TOKEN={access_token}")
                else:
                    updated_lines.append(line)
            env_content = '\n'.join(updated_lines)
        else:
            print("➕ Adding BEEPER_ACCESS_TOKEN to .env...")
            if not env_content.endswith('\n'):
                env_content += '\n'
            env_content += f"\n# Matrix Access Token (extracted from Beeper Desktop)\n"
            env_content += f"BEEPER_ACCESS_TOKEN={access_token}\n"

        # Write back to .env
        env_file.write_text(env_content)
        print(f"   ✓ Updated {env_file}")
        print()

        print("=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
        print()
        print("Your BEEPER_ACCESS_TOKEN has been added to .env")
        print()
        print("⚠️  IMPORTANT SECURITY NOTES:")
        print("   1. Never commit .env to git (it should be in .gitignore)")
        print("   2. This token provides full access to your Matrix account")
        print("   3. Re-run this script if you log out/in to Beeper Desktop")
        print()
        print("Next steps:")
        print("   1. Verify: grep BEEPER_ACCESS_TOKEN .env")
        print("   2. Test extraction: .venv/bin/python test_beeper_extraction.py")
        print()

        return True

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        success = extract_beeper_access_token()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
