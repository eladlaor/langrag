"""
LinkedIn Draft Creator

Sends newsletter content to n8n webhook, which creates a LinkedIn draft post.
Implements fail-soft pattern: pipeline succeeds even if LinkedIn fails.

Provides:
- deliver_to_linkedin(): Standalone helper returning a result dict (used by output_handler)
"""

import os
import logging
import requests
from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
from graphs.state_keys import OrchestratorKeys
from constants import N8N_LINKEDIN_WEBHOOK_URL, TIMEOUT_HTTP_REQUEST

logger = logging.getLogger(__name__)

# LinkedIn post character limit
LINKEDIN_CHAR_LIMIT = 3000


def deliver_to_linkedin(state: ParallelOrchestratorState) -> dict:
    """
    Deliver newsletter content to LinkedIn as a draft post via n8n webhook.

    Standalone helper that returns a result dict with success/failure info.
    Called by output_handler when send_linkedin is in output_actions.

    Args:
        state: ParallelOrchestratorState with consolidated newsletter path and metadata

    Returns:
        dict: {"success": True/False, "draft_response": ..., "error": ...}

    Design:
        - 30-second timeout (fail-fast if n8n hangs)
        - Truncates content to LinkedIn's 3000 char limit
        - Does NOT raise exceptions (fail-soft)
    """
    # LinkedIn draft creation only works with a consolidated newsletter
    newsletter_path = state.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH)

    if not newsletter_path:
        msg = "No consolidated newsletter available for LinkedIn delivery (consolidation may be disabled or only 1 chat processed)"
        logger.info(f"LinkedIn delivery skipped: {msg}")
        return {"success": False, "error": msg}

    if not os.path.exists(newsletter_path):
        msg = f"Newsletter file not found at {newsletter_path}"
        logger.warning(f"LinkedIn delivery skipped: {msg}")
        return {"success": False, "error": msg}

    # Read newsletter content
    try:
        with open(newsletter_path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Failed to read newsletter for LinkedIn delivery: {e}")
        return {"success": False, "error": f"read_error: {e}"}

    if not content or content.strip() == "":
        logger.warning("Newsletter content is empty, skipping LinkedIn delivery")
        return {"success": False, "error": "empty_content"}

    # Enforce LinkedIn character limit
    if len(content) > LINKEDIN_CHAR_LIMIT:
        logger.warning(f"Newsletter content ({len(content)} chars) exceeds LinkedIn limit, truncating to {LINKEDIN_CHAR_LIMIT} chars")
        content = content[: LINKEDIN_CHAR_LIMIT - 3] + "..."

    # Call n8n webhook
    try:
        logger.info("Sending LinkedIn draft request to n8n webhook")
        response = requests.post(N8N_LINKEDIN_WEBHOOK_URL, json={"content": content, "data_source": state.get(OrchestratorKeys.DATA_SOURCE_NAME), "date_range": f"{state[OrchestratorKeys.START_DATE]} to {state[OrchestratorKeys.END_DATE]}"}, timeout=TIMEOUT_HTTP_REQUEST)

        response.raise_for_status()

        logger.info("LinkedIn draft created successfully via n8n webhook")
        draft_response = response.json() if response.text else {}
        return {
            "success": True,
            "draft_response": draft_response,
        }

    except requests.exceptions.Timeout:
        logger.error("n8n webhook timeout (30s) - LinkedIn draft NOT created")
        return {"success": False, "error": "timeout"}

    except requests.exceptions.RequestException as e:
        logger.error(f"n8n webhook error for LinkedIn delivery: {e}")
        return {"success": False, "error": str(e)}

    except Exception as e:
        logger.error(f"Unexpected error in LinkedIn delivery: {e}")
        return {"success": False, "error": f"unexpected: {e}"}


