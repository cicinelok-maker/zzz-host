# ZZZ character progression

Wires the progression tools of [zzz-host](../README.md) into DSH as callable tools.

**This is not a standalone plugin** — it is an MCP client configuration that
connects `zzz-host/tools/zzz_mcp.py`.

> Chinese version: [DETAIL.md](DETAIL.md). **Keep both in sync** — a test
> counts the registered tools and compares them against both files.

---

## What it provides

9 tools covering "look → think → do":

| Tool | What it does | Side effects |
|---|---|---|
| `zzz_environment` | Check environment (paths / OneDragon OCR / character config) | No |
| `zzz_launch` | Make sure the game is running (launch + click through if not) | No |
| `zzz_read_status` | Read one character's current state (discs, skills, level) | No |
| `zzz_read_resource` | Read current battery / materials | No |
| `zzz_plan` | Produce a disc-swap plan for one character | No |
| `zzz_daily_plan` | Produce today's full plan for one character (no game needed) | No |
| `zzz_daily_run` | Run one full progression round. **Requires `confirm=true`** | **Yes** |
| `zzz_scan_roster` | Scan which characters the account actually has (~6 min) | No |
| `zzz_list_agents` | List characters configured in `disc_meta.json` (64) | No |

---

## The difference that matters

`zzz_scan_roster` and `zzz_list_agents` are **not** the same thing:

* `zzz_list_agents` — what the **config library** knows (64 characters)
* `zzz_scan_roster` — what **your account** actually has (needs the game open)

Presenting the library list as if it were the account roster is the single
most common way to confuse a user. Use `zzz_scan_roster` first.
