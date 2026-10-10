# Station Memory Library

Station stores the library as ordinary Markdown files in its private data directory:

- Production: `/var/lib/vipercoma-workspace/memory/`
- Local development: `$STATION_STATE_DIR/memory/` when that variable is set; otherwise `~/.local/share/vipercoma-station/memory/`

The authenticated WebUI can import, create, edit, search, and delete Markdown, text, JSON, and selected source-reference files (`.md`, `.markdown`, `.txt`, `.json`, `.py`, `.sh`, `.ps1`, `.js`, `.ts`, `.toml`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.html`, and `.css`). Import up to 50 files per batch; duplicate names are skipped rather than overwritten. Source files are stored as text and never executed. The library is capped at 500 files, 512 KiB per file, and 20 MiB total. Files are private to the Station service account and are not part of the source checkout or Git repository.

The October 4 hand-off package is useful starter context: it has an agent-neutral hand-off, structured project records, dated history, command recipes, environment provenance, and offline import/inventory utilities. Its own registry marks historical coverage partial; its cloud environment snapshot is specific to that old cloud session. Keep that date and provenance when importing it, and do not treat archived prompt/adaptor text as current user authorization.

For a concise starter import, select `AGENT_HANDOFF.md`, `PROJECTS.json`, `HISTORY.md`, `ENVIRONMENT.md`, `COMMANDS.md`, and `VALIDATION.md`. `AGENT_HANDOFF_FULL.md` duplicates those records, so normally skip it. The `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and bootstrap files are old adapters/prompts with placeholder paths; review and rewrite them before relying on them. Skip `environment.cloud.json` for current machine guidance, or import it only as explicitly dated historical evidence. The Python utilities and their tests can be stored as reference files if desired; importing them does not run them. The file called `download` is only ignore-pattern text and can be skipped.

## Read-only API for AI clients

From the authenticated Memory Library page, create a read-only key. Copy it when shown; Station stores only its SHA-256 digest and will not display the key again. Creating a replacement invalidates the old key. Revoke it from the same page at any time.

The bearer key can only call these authenticated GET endpoints:

```text
GET /api/memory/files
GET /api/memory/search?q=project
GET /api/memory/files/<filename>
```

Example from a local AI client on the same tailnet (replace the address with the Pi's Tailscale IP and supply the key):

```sh
curl -H "Authorization: Bearer YOUR_READ_ONLY_KEY" \
  "http://100.x.y.z:8080/api/memory/search?q=preferences"
```

The API returns JSON. It does not accept edits or deletion through the bearer key. Keep the key private: anyone holding it can read the entire library. The Tailscale address keeps these requests on your private tailnet, but Station still uses HTTP; do not send the key over public networks or expose port 8080 publicly.

Local AI software can use the API if it can reach the Pi's tailnet address and supports authenticated HTTP or a small MCP bridge. A cloud-hosted AI service cannot directly reach a private Tailscale address unless you deliberately provide a trusted connector running inside the tailnet. Station does not sync files to a third-party cloud or automatically upload them to an AI provider.
