# Codex environment

Extract the ZIP and place the complete `travel-planner` folder under the target project's `.agents/skills/` for project-local use. A user-level local install can use `~/.agents/skills/`. Keep assets and references together. Do not replace a same-name existing skill without inspecting it. Invoke `$travel-planner` or choose it in the host's skill UI; if not discovered, refresh/restart as appropriate. These locations were checked against [OpenAI's skills documentation](https://learn.chatgpt.com/docs/build-skills) on 2026-09-21.

Use the selected workspace and quote paths containing spaces. Find an available Python 3.10+ runtime and run preflight for selected formats. If PDF dependencies are absent, use an existing suitable runtime or a task-local virtual environment with requirements when installation is authorized. Do not replace system Python or assume a hardcoded author-machine path. There is no API-key requirement for this package.

Use available document/image and browser tools to inspect original inputs and verify rendered outputs. Internet tools are optional; their absence means research is limited to supplied sources. Refer to actual local output paths in final file links. Serve HTML on localhost only if a browser needs it; a local server is not a shareable public deployment. Hosting/deployment requires a separate user request.

Current file selection controls delivery: HTML-only creates no PDF and checks no PDF dependency. PDF-only creates no HTML dashboard. Both use the same input and coordinator. Do not attach extra JSON or package ZIPs unless asked. The creator's sandbox verification does not certify a recipient's Codex environment.

Photo acquisition is a normal part of a new travelbook. Use this host's actual web/image search and image-inspection tools, then the bundled `media_pipeline.py` for downloaded or local assets. In Codex desktop, use the available bundled Python/Pillow runtime; do not assume that shell `python3` contains Pillow. If a tool is blocked, record the actual reason and disclose the missing photos; do not silently produce a photo-free result as complete.
