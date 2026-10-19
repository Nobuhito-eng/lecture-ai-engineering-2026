"""第1回の回答比較。既定で 2 モデル × 2 質問 × 3 回の計 12 リクエスト。

uv run python -m scripts.day1_compare --models MODEL1 MODEL2
結果は実行ごとに別ファイルへ保存する。API キーや例外の詳細は保存しない。
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import errors, types

from app.ask import DEFAULT_QUESTION
from app.config import MODEL, get_api_key

QUESTIONS = ["LoRAとは何ですか？", DEFAULT_QUESTION]


def run(models: list[str], output: Path, interval: float) -> int:
    """独立した質問を各 3 回送り、成功も失敗も呼び出しごとに追記する。"""
    failures = 0
    with genai.Client(
        api_key=get_api_key(),
        http_options=types.HttpOptions(
            timeout=60000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    ) as client:
        # 誤って過去の結果を上書きしない。
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            first = True
            for model in models:
                for question in QUESTIONS:
                    for repeat in range(1, 4):
                        if not first:
                            time.sleep(interval)
                        first = False
                        record = {
                            "kind": "live_api",
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "model_requested": model,
                            "question": question,
                            "repeat": repeat,
                        }
                        started = time.perf_counter()
                        try:
                            response = client.models.generate_content(
                                model=model, contents=question,
                            )
                            usage = response.usage_metadata
                            record.update(
                                status="ok" if response.text else "no_text",
                                model_returned=response.model_version,
                                answer=response.text,
                                tokens={
                                    name: getattr(usage, name, None)
                                    for name in (
                                        "prompt_token_count", "candidates_token_count",
                                        "thoughts_token_count", "total_token_count",
                                    )
                                },
                            )
                            if not response.text:
                                failures += 1
                        except errors.APIError as exc:
                            record.update(status="api_error", http_status=exc.code)
                            failures += 1
                        except Exception as exc:
                            # 接続エラー等も残すが、URL・ヘッダーを含む詳細は残さない。
                            record.update(status="client_error", error_type=type(exc).__name__)
                            failures += 1
                        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                        stream.flush()
                        print(f"{model} / {question} / {repeat}: {record['status']}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="第1回：モデル別に同じ質問を3回ずつ実行")
    parser.add_argument("--models", nargs="+", default=[MODEL, "gemini-3.8-flash"])
    parser.add_argument("--interval", type=float, default=15.0, help="API 呼び出し間の待機秒数")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("--interval は 0 以上にしてください。")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or Path(f"lectures/01/results/comparison_{stamp}.jsonl")
    failures = run(list(dict.fromkeys(args.models)), output, args.interval)
    print(f"結果: {output} / 失敗・回答なし: {failures}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
