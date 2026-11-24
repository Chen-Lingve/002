# RF Knowledge Workbench Tools

This source-only snapshot contains the `rfkb-review` skill, the `rf_knowledge`
read-only MCP server, the local workbench runtime it depends on, and synthetic
tests. It has no production knowledge, attachments, local client configuration,
or credentials. Treat this snapshot as private unless the owner grants
distribution rights. Vendored Lucide assets retain their license notices.

## Quick start (Windows, Python 3.13)

Run these commands from the snapshot root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe -m unittest discover -q
.\.venv\Scripts\python.exe -m rfkb demo --data ./demo-data
.\.venv\Scripts\python.exe -m rfkb serve --data ./demo-data --port 8766
```

The last command is optional and serves only on loopback. The demo data are
synthetic and must not drive an engineering decision.

## Connect the MCP client

Add a stdio server named `rf_knowledge` in your project's MCP configuration.
Use the absolute path to this virtual environment's Python executable as the
command. Set the arguments to `-m rfkb mcp --data ABSOLUTE_DATA_DIRECTORY`,
substituting the actual path to the chosen local data directory. The client
normally starts this process; no web server is necessary.

For a native project supporting `.agents/skills`, keep the bundled
`.agents/skills/rfkb-review/SKILL.md` under that project's skills directory.
Verify the client exposes `kb_status`, `kb_search`, `kb_get_record`,
`kb_get_context`, `kb_evaluate`, and `kb_get_run`. These tools do not publish or
edit records and cannot retrieve drafts.
