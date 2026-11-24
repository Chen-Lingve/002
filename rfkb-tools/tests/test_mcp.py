import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from rfkb.store import KnowledgeStore
from tests.helpers import fixture, source_payload


class McpTests(unittest.TestCase):
    def test_real_stdio_tools_keep_drafts_private_and_do_not_persist_evaluation(self):
        self.assertIsNotNone(importlib.util.find_spec("rfkb.mcp_server"),
                             "Official MCP boundary is not implemented")
        with tempfile.TemporaryDirectory() as root:
            store = KnowledgeStore(root, test_mode=True)
            source, interface = fixture(store)
            draft = store.create_record(source_payload(source["body"]["artifact_id"]), "Test author")

            async def verify():
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "rfkb", "mcp", "--data", root],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env={"PYTHONIOENCODING": "utf-8"})
                async with stdio_client(params) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        self.assertEqual({t.name for t in tools}, {
                            "kb_search", "kb_get_record", "kb_get_context",
                            "kb_evaluate", "kb_get_run", "kb_status"})
                        self.assertTrue(all(t.annotations.readOnlyHint for t in tools))

                        async def call(name, args):
                            result = await session.call_tool(name, args)
                            if result.isError:
                                return result
                            return result.structuredContent or json.loads(result.content[0].text)

                        found = await call("kb_search", {"query": "中文"})
                        self.assertEqual(found["total"], 1)
                        hidden = await call("kb_get_record", {
                            "record_id": draft["record_id"], "version": 1})
                        self.assertTrue(hidden.isError)
                        profile = {"record_id": interface["record_id"], "version": 1}
                        context = await call("kb_get_context", {"records": [profile]})
                        self.assertEqual(len(context["records"]), 2)
                        result = await call("kb_evaluate", {"request": {
                            "profile": profile, "rules": [], "parameters": {
                                "shaft": {"value": "9.5", "unit": "mm"},
                                "hole": {"value": "10.5", "unit": "mm"}}}})
                        self.assertEqual(result["outcome"], "pass")
                        self.assertNotIn("run_id", result)
                        status = await call("kb_status", {})
                        self.assertEqual(status["runs"], 0)

            asyncio.run(verify())
            self.assertEqual(store.stats()["runs"], 0)
