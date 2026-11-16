"""第5回の条件を固定してAPI呼び出しを記録する。APIキーは環境変数のみ。"""
import json
import os
import subprocess
import time
from pathlib import Path

QUESTIONS = [
    "第2回の説明では、LoRAは何を固定し何を学習しますか？QLoRAは何を加えますか？",
    "第3回の例では、コンパクションとセッションをまたぐメモリはどう違いますか。日々のメモはすべて長期メモリに入りますか",
    "今回作ったRAGの実測平均応答時間と正答率を教えてください",
]
CASES = [(q, label, args, topk, neighbors) for q in range(3) for label, args, topk, neighbors in [
    ("baseline", [], "5", "0"), ("basic", [], "3", "0"), ("neighbors", [], "5", "1")
]] + [(0, label, [mode], "5", "0") for label, mode in [
    ("full", "--full-context"), ("tree", "--tree"), ("graph", "--graph")
]]


def main():
    directory = Path('/tmp/aie-day5-results')
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for index, label, args, topk, neighbors in CASES:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "AIE_MODEL": "gemini-3.5-flash-lite",
               "AIE_RAG_TOP_K": topk, "AIE_RAG_INCLUDE_NEIGHBORS": neighbors}
        record = {"question_id": index + 1, "question": QUESTIONS[index], "condition": label,
                  "top_k": int(topk), "neighbors": neighbors == "1", "attempts": []}
        for attempt in range(2):
            start = time.perf_counter()
            try:
                p = subprocess.run(['uv', 'run', 'python', '-m', 'app.agent', '--trace', *args, QUESTIONS[index]],
                                   capture_output=True, text=True, timeout=55, env=env)
                result = {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
                          "wall_seconds": round(time.perf_counter() - start, 3)}
            except subprocess.TimeoutExpired as exc:
                result = {"returncode": None, "stdout": (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''),
                          "stderr": "timeout", "wall_seconds": round(time.perf_counter() - start, 3)}
            record['attempts'].append(result)
            if result['returncode'] == 0:
                break
            if attempt == 0:
                time.sleep(3)
        records.append(record)
        (directory / 'agent_comparison.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Q{index+1} {label}: exit={result['returncode']} wall={result['wall_seconds']}s attempts={len(record['attempts'])}", flush=True)
    print('EXPERIMENTS_DONE', flush=True)


if __name__ == '__main__':
    main()
