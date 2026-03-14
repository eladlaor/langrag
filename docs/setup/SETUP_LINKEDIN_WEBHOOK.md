# LinkedIn Draft Automation Setup

LangRAG can automatically create LinkedIn draft posts from generated newsletters via an n8n workflow. The pipeline sends the newsletter content to an n8n webhook, which creates a draft post in your LinkedIn account.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Step 1: Create a LinkedIn Developer App](#step-1-create-a-linkedin-developer-app)
- [Step 2: Configure n8n Workflow](#step-2-configure-n8n-workflow)
- [Step 3: Set Up OAuth Credentials](#step-3-set-up-oauth-credentials)
- [Step 4: Test the Integration](#step-4-test-the-integration)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
Newsletter Generation Pipeline
  |
  v
linkedin_draft_creator node (LangGraph)
  |
  v
HTTP POST to n8n webhook
  |
  v
n8n Workflow: Webhook -> LinkedIn Node
  |
  v
LinkedIn API (lifecycleState: "DRAFT")
  |
  v
Draft appears in: LinkedIn -> Start a post -> Drafts
```

Key design decisions:
- **Draft only** -- posts are never auto-published; you review and publish manually
- **Fail-soft** -- the newsletter pipeline succeeds even if LinkedIn draft creation fails
- **Consolidated newsletters only** -- drafts are created from cross-chat consolidated output, not per-chat newsletters

---

## Step 1: Create a LinkedIn Developer App

1. Go to: https://www.linkedin.com/developers/apps
2. Click **"Create app"**
3. Fill in:
   - **App name:** `Newsletter Automation`
   - **LinkedIn Page:** Select your company page (or create one)
   - **App logo:** Optional
4. Go to the **"Auth"** tab:
   - Copy your **Client ID** and **Client Secret**
   - Add OAuth 2.0 redirect URL: `http://localhost:5678/rest/oauth2-credential/callback`
   - Click **"Update"**
5. Go to the **"Products"** tab:
   - Request access for:
     - **"Share on LinkedIn"**
     - **"Sign In with LinkedIn using OpenID Connect"**
   - Approval is usually instant for personal accounts
   - Wait for "Access granted" status

---

## Step 2: Configure n8n Workflow

### Access n8n

```
URL: http://localhost:5678
Login: admin / <your N8N_PASSWORD from .env>
```

### Create the workflow

1. **Add a Webhook Trigger node:**
   - Click "Add node" -> "Webhook"
   - HTTP Method: `POST`
   - Path: `linkedin-draft`
   - Response Code: `200`
   - Response Mode: "On Received"
   - Save

2. **Add a LinkedIn node:**
   - Click "Add node" -> "LinkedIn"
   - Resource: `Post`
   - Operation: `Create`
   - **Lifecycle State: `DRAFT`** (critical -- ensures draft, not published)
   - Text: `{{ $json.body.content }}`
   - Post As: `Person`
   - Visibility: `PUBLIC`
   - Credentials: Click "Create New Credential" (see Step 3)
   - Save

3. **Connect the nodes:**
   - Drag from Webhook -> LinkedIn
   - Workflow should show: `Webhook -> LinkedIn`

4. **Activate the workflow:**
   - Toggle the switch at top right: "Inactive" -> "Active"
   - Webhook URL appears: `http://localhost:5678/webhook/linkedin-draft`

---

## Step 3: Set Up OAuth Credentials

In the n8n UI:

1. Click **"Credentials"** (left sidebar)
2. Click **"Add Credential"**
3. Select: **"LinkedIn OAuth2 API"**
4. Fill in:
   - **Client ID:** (from LinkedIn Developer App)
   - **Client Secret:** (from LinkedIn Developer App)
5. Click **"Connect my account"**
6. A popup opens -> Log in to LinkedIn -> Authorize the app
7. Popup closes -> Credential saved
8. Name it: `LinkedIn Personal Account`
9. Click **"Save"**

**Test the credential:**
- Go back to the LinkedIn node in the workflow
- Select the credential from the dropdown
- Click "Test credential" -> Should show a checkmark

---

## Step 4: Test the Integration

### Manual webhook test (bypasses LangGraph)

```bash
curl -X POST "http://localhost:5678/webhook/linkedin-draft" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Test draft post from newsletter automation",
    "data_source": "test",
    "date_range": "2025-10-01 to 2025-10-22"
  }'
```

Expected: 200 OK response. Check LinkedIn -> Start a post -> Drafts.

### End-to-end test

```bash
curl -X POST "http://localhost:8000/api/generate_periodic_newsletter" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-10-01",
    "end_date": "2025-10-14",
    "data_source_name": "mcp_israel",
    "whatsapp_chat_names_to_include": ["MCP Israel", "MCP Israel #2"],
    "consolidate_chats": true,
    "create_linkedin_draft": true
  }'
```

Check:
- Backend logs: `docker logs langrag-app --tail 50 | grep -i linkedin`
- n8n execution history: http://localhost:5678/executions
- LinkedIn drafts: LinkedIn -> Start a post -> Drafts

---

## Usage

Add `"create_linkedin_draft": true` to any newsletter generation API request:

```json
{
  "start_date": "2025-10-01",
  "end_date": "2025-10-14",
  "data_source_name": "langtalks",
  "whatsapp_chat_names_to_include": ["LangTalks Community", "LangTalks Community 2"],
  "consolidate_chats": true,
  "create_linkedin_draft": true
}
```

The draft will be created after the consolidated newsletter is generated. If consolidation is disabled or only one chat is processed without consolidation, no LinkedIn draft will be created.

---

## Troubleshooting

### Webhook returns 404
- Verify the workflow is activated in n8n (toggle should be ON)
- Check the webhook path matches `linkedin-draft`

### LinkedIn OAuth fails
- Verify the redirect URL in your LinkedIn app matches exactly: `http://localhost:5678/rest/oauth2-credential/callback`
- Verify "Share on LinkedIn" product is approved (Products tab -> "Access granted")
- Try re-authenticating: n8n -> Credentials -> LinkedIn OAuth2 API -> "Reconnect"

### Draft doesn't appear in LinkedIn
- Check the n8n execution log: http://localhost:5678/executions
- Verify the LinkedIn node Lifecycle State is set to `DRAFT` (not `PUBLISHED`)
- Check for API errors in the execution details

### Timeout errors
- Verify n8n is healthy: `docker exec n8n wget -qO- http://localhost:5678/healthz`
- Restart if needed: `docker restart n8n`

### Newsletter succeeds but LinkedIn fails
This is expected behavior (fail-soft design). Check:
- n8n container is running
- Workflow is activated
- OAuth token hasn't expired (re-authenticate in n8n)
