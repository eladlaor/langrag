#!/usr/bin/env python3
"""
Decrypt Beeper keys exported from Web UI

Instructions:
1. Open Beeper Web UI (https://app.beeper.com)
2. All Settings → Security & Privacy → Export E2E room keys
3. Save to: ./secrets/exported_keys/element-keys.txt
4. Run this script

"""

import getpass
import json
import os
import subprocess
import sys
from datetime import datetime
from dotenv import load_dotenv

def decrypt_manual_export():
    """Decrypt a manually exported key file"""
    load_dotenv()

    # Config
    export_password = os.getenv("BEEPER_EXPORT_PASSWORD")
    output_path = os.getenv("DECRYPTED_KEYS_FILE_PATH", "./secrets/decrypted-keys.json")

    # Default to the organized project location
    default_export_file = "./secrets/exported_keys/element-keys.txt"

    print("🔓 Beeper Manual Key Decryption")
    print("=" * 70)
    print()

    # Prompt for export file location
    print("📁 Default export file location:")
    print(f"   {default_export_file}")
    print()
    user_path = input("Press Enter to use default, or enter custom path: ").strip()

    manual_export_file = user_path if user_path else default_export_file

    # Check for manual export file
    if not os.path.exists(manual_export_file):
        print()
        print(f"❌ File not found: {manual_export_file}")
        print()
        print("📝 Instructions:")
        print("  1. Open Beeper WEB UI (https://app.beeper.com)")
        print("  2. All Settings → Security & Privacy → Export E2E room keys")
        print("  3. Download the file from your browser")
        print("  4. Move it to: ./secrets/exported_keys/element-keys.txt")
        print()
        print("  Quick command:")
        print("     mkdir -p ./secrets/exported_keys")
        print("     mv ~/Downloads/element-keys.txt ./secrets/exported_keys/")
        print()
        print("  5. Run this script again")
        return False

    file_size = os.path.getsize(manual_export_file)
    print(f"📄 Found export file ({file_size:,} bytes)")

    # Get export password
    if not export_password:
        print("\n🔑 Enter the password you used when exporting from Beeper:")
        export_password = getpass.getpass("Export password: ")

    # Ensure output dir exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Decrypt
    print("🔓 Decrypting...")
    temp_output = f"temp_decrypted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # Get the script directory to find megolm_backup.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    megolm_script = os.path.join(script_dir, "megolm_backup.py")

    if not os.path.exists(megolm_script):
        print(f"❌ Required script not found: {megolm_script}")
        return False

    try:
        with open(temp_output, 'w') as outfile:
            proc = subprocess.Popen(
                [sys.executable, megolm_script, "--from", manual_export_file, "-p", export_password],
                stdout=outfile,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            print("❌ Decryption failed")
            if stderr:
                print(f"Error: {stderr}")
            return False

        # Validate
        with open(temp_output) as f:
            keys = json.load(f)

        print(f"✅ Decrypted {len(keys):,} key entries")

        # Move to final location
        import shutil
        shutil.move(temp_output, output_path)

        print(f"📁 Keys saved to: {output_path}")

        # Show stats
        unique_rooms = len(set(k['room_id'] for k in keys))
        print("📊 Stats:")
        print(f"   🔑 Total keys: {len(keys):,}")
        print(f"   🏠 Unique rooms: {unique_rooms:,}")
        print(f"   📦 File size: {os.path.getsize(output_path):,} bytes")

        print("\n✅ SUCCESS! Keys are ready for message extraction.")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        # Cleanup temp file
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except:
                pass


if __name__ == "__main__":
    success = decrypt_manual_export()
    print("=" * 60)
    sys.exit(0 if success else 1)
