"""第3回: エージェントに持たせるツール。

ここに書いた関数の docstring と型ヒントが、そのままモデルへの「ツールの説明文」になる。
説明文を書き換えると、モデルがツールを使うかどうか・どんな引数で呼ぶかが変わる。
"""

import json
import random
import re
from datetime import datetime
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_RESULTS = 3

# 第3回 宿題（実装）: 学習ログの保存先。.gitignore 済み。テストでは一時フォルダに差し替える
LEARNING_LOG_DIR = Path(__file__).resolve().parent.parent / "learning_log"
MAX_LOG_TITLE_CHARS = 80
MAX_LOG_CONTENT_CHARS = 20_000


@cache
def load_glossary() -> list[dict]:
    with open(DATA_DIR / "glossary.json", encoding="utf-8") as f:
        return json.load(f)["terms"]


def _normalize(text: str) -> str:
    return text.casefold().replace(" ", "").replace("　", "")


def _names(entry: dict) -> list[str]:
    return [_normalize(entry["term"]), _normalize(entry["id"])] + [
        _normalize(a) for a in entry["aliases"]
    ]


def search_glossary(query: str) -> str:
    """講座の用語集から用語を検索し、定義と、どの回で扱うかを返す。

    AIエンジニアリングの用語や、この講座（AIE2026）に固有の言葉について
    答える前に使うこと。query には調べたい用語を1つだけ入れる（例: "LoRA"）。
    """
    q = _normalize(query)
    if not q:
        return "検索語が空です。調べたい用語を1つ指定してください。"
    glossary = load_glossary()

    exact = [e for e in glossary if q in _names(e)]
    # 「r」のような短い別名が何にでも当たらないよう、名前側が短いものは除く
    partial = [
        e for e in glossary
        if e not in exact and any(q in n or (len(n) >= 3 and n in q) for n in _names(e))
    ]
    in_definition = [
        e for e in glossary
        if e not in exact and e not in partial and q in _normalize(e["definition"])
    ]
    hits = (exact + partial + in_definition)[:MAX_RESULTS]

    if not hits:
        return f"用語集に「{query}」は見つかりませんでした。"
    return json.dumps(
        [
            {
                "term": e["term"],
                "lecture": e["lecture"],
                "definition": e["definition"],
                "related": e["related"],
            }
            for e in hits
        ],
        ensure_ascii=False,
    )


def get_lecture_summary(lecture: int) -> str:
    """指定した回（1始まりの整数）の講義の要点を返す。

    「第3回では何を学ぶ？」のように、回の内容や関係を聞かれたときに使う。
    """
    path = DATA_DIR / "lectures" / f"{lecture:02d}.md"
    if not path.exists():
        available = sorted(p.stem for p in (DATA_DIR / "lectures").glob("*.md"))
        return f"第{lecture}回の要点はまだありません。用意されている回: {', '.join(available)}"
    return path.read_text(encoding="utf-8")


def make_quiz(lecture: int) -> str:
    """指定した回の用語集から用語を1つ選び、確認問題と答えを返す。

    「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う。
    lecture には回の番号（1始まりの整数）を入れる。
    """
    terms = [e for e in load_glossary() if e["lecture"] == lecture]
    if not terms:
        available = sorted({e["lecture"] for e in load_glossary()})
        return (
            f"第{lecture}回の用語は用語集にありません。"
            f"問題を作れる回: {', '.join(f'第{n}回' for n in available)}"
        )
    term = random.choice(terms)
    return json.dumps(
        {
            "lecture": lecture,
            "question": f"「{term['term']}」の意味は？",
            "answer": term["definition"],
        },
        ensure_ascii=False,
    )


def _log_filename(title: str, now: datetime) -> str:
    """タイトルからファイル名を作る。文字・数字・ハイフン以外（/ や . を含む）は - に置き換える。"""
    slug = re.sub(r"[^\w\-]+", "-", title).strip("-_")[:40] or "log"
    return f"{now:%Y%m%d-%H%M%S}_{slug}"


def save_learning_log(title: str, content: str, lecture: int = 0) -> str:
    """学習の記録を learning_log/ フォルダに Markdown ファイルとして保存する。

    利用者が「学習ログに残して」「今日の学びを記録して」のように、記録や保存をはっきり
    頼んだときだけ使う。質問に答えるだけのときは使わない。
    実行の前に利用者の承認が必要で、拒否されたら保存されない。
    title には記録の短い見出し（例: "LoRAとQLoRAの違い"）、content には記録する本文
    （Markdown 可）、lecture には関係する回の番号（1始まりの整数。分からなければ 0）を入れる。
    """
    title, content = title.strip(), content.strip()
    if not title or not content:
        return "保存していません。title と content の両方を指定してください。"
    if len(title) > MAX_LOG_TITLE_CHARS or len(content) > MAX_LOG_CONTENT_CHARS:
        return (
            f"保存していません。title は{MAX_LOG_TITLE_CHARS}文字以内、"
            f"content は{MAX_LOG_CONTENT_CHARS}文字以内にしてください。"
        )

    log_dir = LEARNING_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    base = _log_filename(title, now)
    lines = [f"# {title}", "", f"- 日時: {now.isoformat(timespec='seconds')}"]
    if lecture > 0:
        lines.append(f"- 関係する回: 第{lecture}回")
    text = "\n".join(lines) + "\n\n" + content + "\n"

    # 既存の記録は上書きしない（同じ秒・同じタイトルなら連番を付ける）
    for n in range(1, 100):
        path = log_dir / (f"{base}.md" if n == 1 else f"{base}_{n}.md")
        try:
            with open(path, "x", encoding="utf-8") as f:
                f.write(text)
        except FileExistsError:
            continue
        return f"学習ログを保存しました: {log_dir.name}/{path.name}"
    return "保存していません。同じ名前のファイルが多すぎます。"
