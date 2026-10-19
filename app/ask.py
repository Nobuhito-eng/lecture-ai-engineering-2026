"""第1回: LLMへの単発質問と、履歴を保つ対話。

使い方:
    uv run python -m app.ask "LoRAとは何ですか？"
    uv run python -m app.ask            # 質問を省略すると、講座に固有の質問をする
    uv run python -m app.ask --chat     # /exit または Ctrl+D で終了

通常はツールも会話履歴も持たない「素の」呼び出し。
講座に固有のことを聞くと、「分からない」と答えるか、一般論でもっともらしく答える
（講座の実際とは違う）ことを確かめよう。
（第3回で、用語集を検索できるエージェントにして改善する）
"""

import argparse

from google import genai
from google.genai import errors

from app.config import MODEL, api_error_message, get_api_key

# 講座に固有の質問。正しい答えは data/glossary.json の homework-levels にある
DEFAULT_QUESTION = "AIE2026の講座の宿題にある「3レベル」とは何ですか？"


def print_usage(response) -> None:
    usage = response.usage_metadata
    prompt = usage.prompt_token_count if usage else None
    output = usage.candidates_token_count if usage else None
    # 未取得の値を 0 と表示すると、実測値と区別できなくなる。
    print(f"[tokens] input={prompt if prompt is not None else '不明'} "
          f"output={output if output is not None else '不明'}")


def ask(question: str) -> str:
    with genai.Client(api_key=get_api_key()) as client:
        response = client.models.generate_content(model=MODEL, contents=question)
        print_usage(response)
        return response.text or "テキストの回答がありませんでした。"


def chat(first_question: str | None = None) -> None:
    """同じ SDK のチャットに質問を送り、利用者とモデルの履歴を引き継ぐ。"""
    with genai.Client(api_key=get_api_key()) as client:
        session = client.chats.create(model=MODEL)
        print("会話モードです。/exit で終了します。履歴はこの実行中だけ保持します。")
        question = first_question
        while True:
            if question is None:
                try:
                    question = input("質問> ")
                except (EOFError, KeyboardInterrupt):
                    print("\n終了しました。")
                    return
            question = question.strip()
            if question.lower() in {"/exit", "/quit"}:
                return
            if question:
                try:
                    response = session.send_message(question)
                    print(response.text or "テキストの回答がありませんでした。")
                    print_usage(response)
                except errors.APIError as e:
                    # API の詳細には秘密情報が含まれうるため、状態コードだけ使う。
                    print(api_error_message(e.code))
            question = None


def main() -> None:
    parser = argparse.ArgumentParser(description="LLMに質問する（--chat で連続対話）")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--chat", action="store_true", help="会話履歴を保って質問を続ける")
    args = parser.parse_args()

    print(f"[model] {MODEL}")
    try:
        if args.chat:
            chat(args.question)
        else:
            question = args.question or DEFAULT_QUESTION
            print(f"[質問] {question}\n")
            print(ask(question))
    except errors.APIError as e:
        print(api_error_message(e.code))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
