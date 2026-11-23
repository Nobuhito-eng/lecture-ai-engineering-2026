"""第6回: 用語集と各回の要点を MCP サーバーとして公開する。

使い方:
    uv run python -m app.mcp_agent --list-tools     # このサーバーが公開するツールを一覧する（APIキー不要）
    uv run python -m app.mcp_server --http          # Streamable HTTP で起動する（http://127.0.0.1:8000/mcp）

引数なしで実行すると stdio（標準入出力）で待ち受ける。これは MCP クライアント（app.mcp_agent など）が
サブプロセスとして起動する使い方なので、手で実行すると入力待ちのまま止まって見える。

第3回では tools.py の関数を agent.py に直接登録した。MCP サーバーにすると、同じ関数を
エージェントのプログラム（app/mcp_agent.py）からも、MCP に対応したほかのソフトウェアからも、
共通の手順で使えるようになる。
"""

import argparse

from mcp.server.mcpserver import MCPServer

from app import tools

# サーバーの名前と説明。クライアントに表示される（設定ファイル側のキー "glossary" とは別物）
server = MCPServer(
    "aie2026-glossary",
    instructions="AIE2026（AIエンジニアリング実践講座）の用語集と各回の要点を提供する。",
)

# 第3回と同じ関数を、そのまま MCP のツールとして公開する。docstring と型ヒントが説明文になる
server.tool()(tools.search_glossary)

# TODO(宿題・基礎): get_lecture_summary も公開しよう
server.tool()(tools.get_lecture_summary)


@server.tool()
def make_quiz(lecture: int) -> str:
    """指定した回の用語をもとに、理解を確かめるクイズを最大3問作る。

    講座の復習やクイズを求められたときに使う。lecture は第何回かを表す整数。
    用語集に登録された回のみ対応し、登録がない回は利用可能な回を返す。
    各問題は用語の説明を求める形式で、解答は含めない。
    """
    glossary = tools.load_glossary()
    available = sorted({entry["lecture"] for entry in glossary})
    if not available:
        return "用語集が空のため、クイズを作れません。"

    available_text = "、".join(f"第{number}回" for number in available)
    if lecture < available[0] or lecture > available[-1]:
        return f"第{lecture}回は範囲外です。クイズを作れる回：{available_text}。"

    entries = [entry for entry in glossary if entry["lecture"] == lecture]
    if not entries:
        return (
            f"第{lecture}回の用語は用語集に登録されていないため、クイズを作れません。"
            f"クイズを作れる回：{available_text}。"
        )

    questions = [
        f"{number}. 「{entry['term']}」とは何か、説明してください。"
        for number, entry in enumerate(entries[:3], start=1)
    ]
    return "\n".join([f"第{lecture}回の復習クイズ", *questions])


def main() -> None:
    parser = argparse.ArgumentParser(description="用語集 MCP サーバー")
    parser.add_argument("--http", action="store_true", help="Streamable HTTP で起動する（既定は stdio）")
    args = parser.parse_args()
    if args.http:
        print("MCP サーバーを http://127.0.0.1:8000/mcp で起動します（Ctrl+C で停止）")
        server.run(transport="streamable-http")
    else:
        # stdio では標準出力がプロトコルの通信路になるので、print してはいけない
        server.run()


if __name__ == "__main__":
    main()
