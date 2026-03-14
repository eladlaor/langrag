#!/usr/bin/env python3
"""
Extract Beeper E2EE keys directly from local SQLite/IndexedDB storage
This is the SIMPLEST method - no API calls, no manual export needed!

This script reads keys from:
- ~/.config/BeeperTexts/account.db (SQLite)
- ~/.config/BeeperTexts/IndexedDB/ (LevelDB)

The keys are already on your system - we just need to extract them.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv


class BeeperLocalKeyExtractor:
    """Extract keys from Beeper's local storage"""

    def __init__(self):
        load_dotenv('.env.dev')

        self.beeper_config = Path.home() / '.config' / 'BeeperTexts'
        self.account_db = self.beeper_config / 'account.db'
        self.index_db = self.beeper_config / 'index.db'
        self.output_path = Path(os.getenv('DECRYPTED_KEYS_FILE_PATH', './secrets/decrypted-keys.json'))

        # Create output directory
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def check_beeper_running(self) -> bool:
        """Check if Beeper is running"""
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'beeper'], capture_output=True)
        return result.returncode == 0

    def extract_from_account_db(self) -> Optional[Dict]:
        """Extract keys from account.db SQLite database"""
        print(f"📂 Reading from: {self.account_db}")

        if not self.account_db.exists():
            print(f"❌ Database not found: {self.account_db}")
            return None

        try:
            conn = sqlite3.connect(f"file:{self.account_db}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Check for megolm backup
            cursor.execute("""
                SELECT key, value FROM store
                WHERE key LIKE '%megolm%' OR key LIKE '%crypto%'
            """)

            keys_data = {}
            for key, value in cursor.fetchall():
                print(f"  📌 Found: {key}")

                # Try to parse JSON value
                try:
                    if value:
                        parsed = json.loads(value)
                        keys_data[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    # Binary data or non-JSON
                    keys_data[key] = f"<binary: {len(value) if value else 0} bytes>"

            conn.close()

            return keys_data if keys_data else None

        except sqlite3.Error as e:
            print(f"❌ SQLite error: {e}")
            return None

    def extract_megolm_backup(self) -> Optional[Dict]:
        """Extract Megolm backup data from store"""
        print("\n🔍 Looking for Megolm backup...")

        try:
            conn = sqlite3.connect(f"file:{self.account_db}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Get megolm backup
            cursor.execute("""
                SELECT value FROM store
                WHERE key = 'ad:m.megolm_backup.v1'
            """)

            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                backup_data = json.loads(row[0])
                print(f"✅ Found Megolm backup:")
                print(f"   Algorithm: {backup_data.get('algorithm', 'unknown')}")
                print(f"   Auth data: {'yes' if backup_data.get('auth_data') else 'no'}")
                return backup_data
            else:
                print("⚠️  No Megolm backup found")
                return None

        except Exception as e:
            print(f"❌ Error reading backup: {e}")
            return None

    def extract_room_keys_from_index_db(self) -> Optional[Dict]:
        """Try to extract room-specific encryption keys from index.db"""
        print(f"\n📂 Reading from: {self.index_db}")

        if not self.index_db.exists():
            print(f"❌ Database not found: {self.index_db}")
            return None

        try:
            conn = sqlite3.connect(f"file:{self.index_db}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Check for encrypted message events
            cursor.execute("""
                SELECT COUNT(*) FROM mx_events
                WHERE type = 'm.room.encrypted'
                LIMIT 1
            """)

            encrypted_count = cursor.fetchone()[0]
            print(f"  📊 Encrypted events: {encrypted_count}")

            # The actual decryption keys are not in index.db
            # They're in the IndexedDB LevelDB store

            conn.close()
            return None

        except sqlite3.Error as e:
            print(f"❌ SQLite error: {e}")
            return None

    def check_for_alternative_solution(self):
        """Print information about alternative approaches"""
        print("\n" + "=" * 60)
        print("🔍 Analysis Complete")
        print("=" * 60)
        print()
        print("The E2EE session keys are stored in Beeper's encrypted storage:")
        print(f"  📁 {self.beeper_config / 'IndexedDB' / 'file__0.indexeddb.leveldb'}")
        print()
        print("These keys are encrypted at rest using:")
        print("  🔐 ChaCha20Poly1305 encryption")
        print("  🔑 Key protected by system keyring")
        print()
        print("=" * 60)
        print("💡 RECOMMENDED SOLUTION")
        print("=" * 60)
        print()
        print("Since Beeper doesn't expose a UI option to export keys,")
        print("and the IndexedDB is encrypted, here are your best options:")
        print()
        print("Option 1: Use MCP for Live Extraction (RECOMMENDED)")
        print("  ✅ No key export needed")
        print("  ✅ Always has latest keys")
        print("  ✅ Uses Beeper's decryption automatically")
        print("  → See: knowledge/setup/beeper_extraction_setup.md")
        print()
        print("Option 2: Use Matrix API with matrix-nio")
        print("  • Connect to Matrix homeserver directly")
        print("  • Export keys programmatically via API")
        print("  • Requires BEEPER_ACCESS_TOKEN")
        print("  → Script: beeper_export_keys_auto.py")
        print()
        print("Option 3: Access Beeper's Internal Crypto Store")
        print("  • Read from IndexedDB LevelDB using ccl_chromium_reader")
        print("  • Decrypt using system keyring")
        print("  • Most complex but fully automated")
        print()
        print("=" * 60)
        print()
        print("❓ Which approach would you like to pursue?")

    def run(self) -> bool:
        """Run the extraction"""
        print("🔓 Beeper Local Key Extraction")
        print("=" * 60)
        print()

        # Check if Beeper is running
        if self.check_beeper_running():
            print("⚠️  Beeper is currently running")
            print("   For best results, close Beeper Desktop first")
            print("   (Continuing anyway...)")
            print()

        # Try various extraction methods
        megolm_backup = self.extract_megolm_backup()
        account_keys = self.extract_from_account_db()
        index_keys = self.extract_room_keys_from_index_db()

        # Show what we found
        if megolm_backup or account_keys:
            print("\n✅ Found some cryptographic data in SQLite databases")
            print("   However, the actual E2EE session keys are stored separately")
            print("   in the encrypted IndexedDB LevelDB store.")

        # Provide guidance
        self.check_for_alternative_solution()

        return False  # We haven't successfully extracted keys yet


def main():
    """Main entry point"""
    extractor = BeeperLocalKeyExtractor()
    extractor.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
