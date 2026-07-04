---
name: podcast-setup
description: |
  Set up or troubleshoot access to the LangTalks podcast MCP server (langrag).
  Use when the user says "set up langrag", "podcast key", "langrag api key",
  "connect to the podcasts", right after installing the langrag-podcasts
  plugin, or when mcp__langrag__* tools fail with 401/unauthorized or
  quota/rate-limit errors.
---

# LangTalks Podcast MCP — Setup and Troubleshooting

The plugin connects to the public MCP server at `https://mcp.langrag.ai/mcp`
(Streamable HTTP). Access requires a free personal API key, read from the
`LANGRAG_MCP_API_KEY` environment variable. The podcast content lives on the
server and is updated there when new episodes are released — the plugin never
needs a content update.

## First-time setup

Walk the user through these steps, running the local ones for them:

1. **Get a key.** Open https://langrag.ai/podcasts, enter an email address,
   and click the verification link that arrives (valid for a limited time).
   The page then shows the API key ONCE — tell the user to copy it immediately.
2. **Set the environment variable.** Append to the user's shell profile
   (ask which shell if unclear; never overwrite the file):

   ```bash
   export LANGRAG_MCP_API_KEY="<the key>"
   ```

   Remind the user the key is a secret: shell profile or a secrets manager,
   never committed to a repo.
3. **Restart Claude Code** (or run `/mcp` and reconnect) so the new
   environment variable is picked up by the MCP connection.
4. **Verify.** Call the `mcp__langrag__list_podcasts` tool. A successful
   response lists the available podcasts with chunk counts and date coverage.
   Then try a real query via `mcp__langrag__search_podcasts`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 401 / "Invalid or missing MCP API key" | `LANGRAG_MCP_API_KEY` unset in the environment Claude Code was launched from, or the key was mistyped/revoked | Re-export the variable and restart; if the key is lost, redo the email verification at https://langrag.ai/podcasts — re-verifying ROTATES the key (the old one stops working) |
| Quota error from a tool call | The per-key daily query budget is exhausted | Wait for the UTC day to roll over; budgets are per key |
| Rate-limit error | Too many queries per minute | Slow down; retry after a short pause |
| Tools not listed at all | Plugin's MCP server not connected | Run `/mcp` to check the `langrag` server status; confirm the plugin is enabled in `/plugin` |
| Date-range validation error | Malformed or inverted `date_start`/`date_end` | Use YYYY-MM-DD and ensure start <= end |

## Notes

- The key is scoped to podcast search only (`search_podcasts`,
  `list_podcasts`). It cannot access any other langrag.ai functionality.
- Searches run on the server; answers are composed by YOUR agent on YOUR
  model. The server never spends its own LLM tokens generating answers.
