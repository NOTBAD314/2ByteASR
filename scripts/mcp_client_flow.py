"""Official MCP Python SDK client for the 兔白字幕 end-to-end check (2026-10-12).

Spawns the product's stdio MCP server exactly like a desktop client would and
runs one phase, writing every step to <out>/client-<phase>.json:

  full    discover → read → search → preview → apply (user approves in the app)
          → change visible → undo (approved) → reject path → export twice
  stale   preview, wait for the app to change the project, apply → refused
  revoked any call after access was revoked → refused

usage: mcp_client_flow.py --phase full --out DIR --server-json '["exe", "--mcp-stdio"]' [--env-json '{...}']
"""
import argparse
import asyncio
import json
import time
import traceback
from pathlib import Path


async def run(phase, out: Path, command, env):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    log = dict(phase=phase, steps=[], started=time.time())

    def step(name, **values):
        log["steps"].append(dict(name=name, t=round(time.time() - log["started"], 3), **values))
        (out / f"client-{phase}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1, default=str), "utf-8")

    params = StdioServerParameters(command=command[0], args=command[1:], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            step("initialize", protocol=init.protocol_version, server=init.server_info.name,
                 version=init.server_info.version)

            async def tool(tool_name, **args):
                result = await session.call_tool(tool_name, args)
                text = result.content[0].text if result.content else ""
                if result.is_error:
                    step(f"{tool_name}:error", error=text[:400])
                    return None
                value = result.structured_content or json.loads(text)
                step(tool_name, result=value)
                return value

            if phase == "full":
                tools = (await session.list_tools()).tools
                step("list_tools", tools=sorted(t.name for t in tools),
                     read_only=sorted(t.name for t in tools if t.annotations and t.annotations.read_only_hint))
                status = await tool("get_status")
                await tool("list_projects")
                page = await tool("get_cues", offset=0, limit=5)
                await tool("search_cues", query=page["cues"][0]["text"][:2])
                await tool("get_speakers")
                await tool("get_alignment_status", limit=5)
                first = page["cues"][0]
                plan = await tool("preview_text_edits", edits=[{"cue_id": first["id"], "text": first["text"] + "（MCP）",
                                                                "translation": (first["translation"] or "") + "（MCP）"}])
                applied = await tool("apply_plan", plan_id=plan["plan_id"], wait_seconds=90)
                again = await tool("apply_plan", plan_id=plan["plan_id"])          # single use
                (out / "client-applied.flag").write_text(first["id"], "utf-8")
                # The app checks the visible change, then signals with a flag file.
                for _ in range(600):
                    if (out / "app-saw-change.flag").exists():
                        break
                    await asyncio.sleep(0.1)
                undone = await tool("undo_plan", plan_id=plan["plan_id"], wait_seconds=90)
                plan2 = await tool("preview_role_changes", organize=True)
                rejected = await tool("apply_plan", plan_id=plan2["plan_id"], wait_seconds=90)
                export1 = await tool("export_subtitles", layers=["original", "bilingual"], name="mcp-demo")
                export2 = await tool("export_subtitles", layers=["original"], name="mcp-demo")
                bad = await tool("export_subtitles", layers=["original"], name="..\\..\\outside")
                log["summary"] = dict(project_cues=(status.get("project") or {}).get("cues"),
                                      applied=(applied or {}).get("status"), reuse_refused=again is None,
                                      undone=(undone or {}).get("status"), rejected=(rejected or {}).get("status"),
                                      export_files=[f["file"] for f in (export1 or {}).get("files", []) + (export2 or {}).get("files", [])],
                                      bad_name_refused=bad is None)
            elif phase == "stale":
                page = await tool("get_cues", offset=0, limit=3)
                target = page["cues"][2]
                plan = await tool("preview_text_edits", edits=[{"cue_id": target["id"], "text": target["text"] + "!"}])
                (out / "client-previewed.flag").write_text(plan["plan_id"], "utf-8")
                for _ in range(600):
                    if (out / "app-edited.flag").exists():
                        break
                    await asyncio.sleep(0.1)
                stale = await tool("apply_plan", plan_id=plan["plan_id"])
                log["summary"] = dict(stale_refused=stale is None)
            elif phase == "revoked":
                status = await tool("get_status")
                log["summary"] = dict(refused=status is None)
            step("done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=("full", "stale", "revoked"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--server-json", required=True)
    parser.add_argument("--env-json", default="{}")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.phase, args.out, json.loads(args.server_json), json.loads(args.env_json)))
    except BaseException:
        (args.out / f"client-{args.phase}.error.txt").write_text(traceback.format_exc(), "utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
