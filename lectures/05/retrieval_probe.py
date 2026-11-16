"""生成を使わず検索結果を比較する。APIによる検索の実行記録用。"""
import json
import time
from pathlib import Path
from app.retrieval import search, add_neighbor_pages, load_pages

QUESTIONS = [
    "第2回の説明では、LoRAは何を固定し何を学習しますか？QLoRAは何を加えますか？",
    "第3回の例では、コンパクションとセッションをまたぐメモリはどう違いますか。日々のメモはすべて長期メモリに入りますか",
    "今回作ったRAGの実測平均応答時間と正答率を教えてください",
]


def describe(pages):
    return [{k: p[k] for k in ("page_id", "document_id", "page", "title", "distance", "neighbor_of", "page_offset") if k in p} for p in pages]


def main():
    records = []
    corpus = load_pages()
    for question in QUESTIONS:
        started = time.perf_counter()
        hits = search(question)
        elapsed = time.perf_counter() - started
        assert len(hits) == 5
        extended = add_neighbor_pages(hits, corpus)
        records.append({"question": question, "seconds_for_top5_with_embedding": round(elapsed, 3),
                        "top5": describe(hits), "top3": describe(hits[:3]), "top5_with_neighbors": describe(extended)})
    out = Path('/tmp/aie-day5-results/retrieval_comparison.json')
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records, ensure_ascii=False))


if __name__ == '__main__':
    main()
