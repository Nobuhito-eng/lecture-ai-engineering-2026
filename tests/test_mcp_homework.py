"""宿題で追加したツールを、実際の MCP 通信を通して確認する。"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent.parent


def test_homework_tools_over_mcp():
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            cwd=ROOT,
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {"get_lecture_summary", "make_quiz"} <= {t.name for t in tools.tools}

                async def call(name, lecture):
                    result = await session.call_tool(name, {"lecture": lecture})
                    assert not result.is_error
                    assert len(result.content) == 1
                    return result.content[0].text

                summary = await call("get_lecture_summary", 2)
                expected = (ROOT / "data/lectures/02.md").read_text(encoding="utf-8")
                assert summary.strip() == expected.strip()

                quiz = await call("make_quiz", 2)
                terms = json.loads((ROOT / "data/glossary.json").read_text(encoding="utf-8"))["terms"]
                lecture_terms = [t["term"] for t in terms if t["lecture"] == 2][:3]
                assert "第2回" in quiz and len(lecture_terms) == 3
                assert all(term in quiz for term in lecture_terms)

                missing = await call("make_quiz", 5)
                assert "第5回" in missing and "登録されていない" in missing
                assert "第2回" in missing

                out_of_range = await call("make_quiz", 99)
                assert "第99回" in out_of_range and "範囲外" in out_of_range
                assert "第2回" in out_of_range

    asyncio.run(check())
