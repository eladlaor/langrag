# Beeper Setup Guide

LangRAG reads WhatsApp messages through [Beeper](https://www.beeper.com/), which bridges WhatsApp to the Matrix protocol with end-to-end encryption.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Create a Beeper Account](#step-1-create-a-beeper-account)
- [Step 2: Export Encryption Keys](#step-2-export-encryption-keys)
- [Step 3: Configure Environment Variables](#step-3-configure-environment-variables)
- [Step 4: Verify Setup](#step-4-verify-setup)
- [How Decryption Works](#how-decryption-works)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- A Beeper account ([beeper.com](https://www.beeper.com/))
- WhatsApp linked to Beeper (via the Beeper app)
- Docker running with LangRAG services

---

## Step 1: Create a Beeper Account

1. Sign up at [beeper.com](https://www.beeper.com/)
2. Download Beeper Desktop or use the Web UI
3. Link your WhatsApp account through Beeper's bridge setup
4. Verify messages are syncing (you should see your WhatsApp chats in Beeper)

---

## Step 2: Export Encryption Keys

E2E key export is **only available in Beeper Web UI** (not Desktop).

1. **Create the secrets directory:**
   ```bash
   mkdir -p ./secrets/exported_keys
   ```

2. **Open Beeper Web UI:**
   - Go to: https://app.beeper.com
   - Log in with your credentials

3. **Navigate to encryption settings:**
   - Click your profile icon (top left or bottom left)
   - Click **"All Settings"**
   - Click **"Security & Privacy"** in the left sidebar
   - Scroll to the **"Encryption"** section

4. **Export keys:**
   - Click **"Export E2E room keys"**
   - Set a password (remember this!) -- e.g., `mypassword123`
   - Click "Export" or "Download"
   - Save the file to: `./secrets/exported_keys/element-keys.txt`

---

## Step 3: Configure Environment Variables

Add these to your `.env` file:

```bash
# Beeper credentials
BEEPER_EMAIL=your_email@example.com
BEEPER_PASSWORD=your_beeper_password

# Encryption key password (from Step 2)
BEEPER_EXPORT_PASSWORD=mypassword123
```

Optional (for server-side key backup -- more reliable):

```bash
# Recovery code from Beeper app > Settings > Security > Reset Secure Storage
# Or from your password manager / iCloud Keychain / Google Password Manager
BEEPER_RECOVERY_CODE=your_recovery_code_here
```

---

## Step 4: Verify Setup

Start the services and run a test extraction:

```bash
docker compose up -d

# Test with a single chat
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-01-01",
    "end_date": "2025-01-07",
    "data_source_name": "your_community",
    "whatsapp_chat_names_to_include": ["Your Chat Name"],
    "desired_language_for_summary": "english",
    "summary_format": "langtalks_format",
    "consolidate_chats": false
  }'
```

You should see in the logs:
```
Auto-decrypted X keys to ./secrets/decrypted-keys.json
Successfully decrypted X/Y messages
```

---

## How Decryption Works

The system uses a **three-tier fallback** (automatic, no user action needed after setup):

| Priority | Method | Source |
|----------|--------|--------|
| 1 | Server backup | `BEEPER_RECOVERY_CODE` (if set) |
| 2 | Manual export | `element-keys.txt` + `BEEPER_EXPORT_PASSWORD` |
| 3 | Persistent session | Auto-saved from recent syncs |

- **Past messages**: Decrypted via exported keys or server backup
- **Future messages**: Decrypted via persistent session (fully automatic)
- After initial setup, no further manual steps are needed

---

## Troubleshooting

### "Cannot auto-decrypt: BEEPER_EXPORT_PASSWORD not set"
- Add `BEEPER_EXPORT_PASSWORD=<your_password>` to `.env`
- Make sure the password matches what you used during export

### "Decryption failed: wrong password or corrupted data"
- Check that `BEEPER_EXPORT_PASSWORD` is correct
- Re-export keys from Beeper Web UI if needed

### "No exported keys file found"
- Verify file exists at `./secrets/exported_keys/element-keys.txt`
- Re-export from Beeper Web UI

### "Decrypted 0/N messages"
- Keys might be too old -- export fresh keys
- Make sure Beeper is synced and up-to-date before exporting

### Security Notes

Keep these files secure (all are in `.gitignore`):
- `./secrets/exported_keys/element-keys.txt` -- Encrypted export
- `./secrets/decrypted-keys.json` -- Decrypted keys
- `.env` with `BEEPER_EXPORT_PASSWORD`
