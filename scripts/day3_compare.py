"""第3回 演習・宿題（基礎・実装）を Gemini で実行し、結果を lectures/03/results/ に保存する。

使い方（Codespaces で、リポジトリの直下から）:
    uv run --frozen python -m scripts.day3_compare --dry-run   # 実行内容と変更箇所の差分だけ表示（APIキー不要）
    uv run --frozen python -m scripts.day3_compare             # 全部実行（10分前後）
    uv run --frozen python -m scripts.day3_compare --reps 1    # 各条件1回だけ（利用枠が少ないとき）
    uv run --frozen python -m scripts.day3_compare --summarize # 保存済みの結果から要約だけ作り直す

基礎: app/agent.py の INSTRUCTIONS か、app/tools.py の docstring を「1か所だけ」変えた変種を作り、
      同じ質問を同じ回数ずつ実行して、ツールの呼ばれ方・回数・引数と回答を記録する。
      app/ のファイルは書き換えない（変種はこのスクリプトの中で組み立てる）。
実装: 本物の CLI（python -m app.agent --trace）に y / n を入力し、保存前の確認の流れを記録する。

途中で止まっても、もう一度実行すれば成功済みの組み合わせは飛ばして続きから実行する。
1日あたりの上限（429 の PerDay）に達したら、その時点で止めて要約を書く。
"""

import argparse
import contextlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import unified_diff
from importlib import metadata
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app import tools
from app.agent import INSTRUCTIONS, agent as course_agent, print_trace, run_with_approval
from app.config import MODEL

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "lectures" / "03" / "results"
RUNS_FILE = RESULTS_DIR / "day3_runs.jsonl"
JST = timezone(timedelta(hours=9))

# app/agent.py と同じ順・同じ設定で登録する（tests/test_day3_compare.py で一致を確かめる）
TOOLS = [
    (tools.search_glossary, False),
    (tools.get_lecture_summary, False),
    (tools.make_quiz, False),
    (tools.save_learning_log, True),  # requires_approval
]

QUESTIONS = {
    "levels": "AIE2026の講座の宿題にある「3レベル」とは何ですか？",  # 第1回と同じ質問（演習 手順2）
    "lora": "LoRAとQLoRAの違いは？",  # 演習 手順3
    "quiz": "第2回の内容から確認問題を1問出して",  # 演習 手順5
}
SAVE_QUESTION = "LoRAとQLoRAの違いを用語集で調べて、学習ログに保存して"  # 宿題（実装）


@dataclass(frozen=True)
class Variant:
    name: str
    label: str
    target: str  # "-"（変更なし）/ "INSTRUCTIONS" / "docstring:<ツール名>"
    old: str
    new: str
    questions: tuple[str, ...]


BASELINE = Variant("baseline", "変更なし（演習・実装を終えた状態）", "-", "", "", ("levels", "lora", "quiz"))
VARIANTS = [
    BASELINE,
    Variant(
        "no_must_search",
        "INSTRUCTIONS から「必ず search_glossary で用語集を確認する」の行を消す",
        "INSTRUCTIONS",
        "- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。\n",
        "",
        ("levels", "lora"),
    ),
    Variant(
        "search_bulk",
        "search_glossary の docstring の「1つだけ」を「まとめて」に変える",
        "docstring:search_glossary",
        'query には調べたい用語を1つだけ入れる（例: "LoRA"）。',
        'query には調べたい用語をまとめて入れる（例: "LoRA QLoRA"）。',
        ("lora",),
    ),
    Variant(
        "no_lecture_ref",
        "INSTRUCTIONS から「回答の最後に、関係する回（第N回）を示す」の行を消す",
        "INSTRUCTIONS",
        "- 回答の最後に、関係する回（第N回）を示す。\n",
        "",
        ("levels", "lora"),
    ),
    Variant(
        "no_quiz_line",
        "INSTRUCTIONS から「確認問題を求められたら make_quiz を使う」の行を消す（docstring だけで呼ばれるか）",
        "INSTRUCTIONS",
        "- 確認問題を求められたら make_quiz を使う。\n",
        "",
        ("quiz",),
    ),
]
VARIANTS_BY_NAME = {v.name: v for v in VARIANTS}


# --- 変種の組み立て -------------------------------------------------------------


def _replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"置き換え対象が {count} 箇所あります（1箇所である必要があります）: {old!r}")
    return text.replace(old, new)


def tool_descriptions(target: Agent) -> dict[str, str]:
    """モデルに渡るツールの説明文（docstring から作られたもの）を取り出す。LLM は呼ばない。"""
    model = TestModel(call_tools=[])
    target.run_sync("ツール一覧", model=model)
    return {t.name: t.description or "" for t in model.last_model_request_parameters.function_tools}


def variant_texts(variant: Variant) -> tuple[str, dict[str, str]]:
    """変種の INSTRUCTIONS と、上書きするツール説明文（docstring 変種のときだけ）を返す。"""
    if variant.target == "-":
        return INSTRUCTIONS, {}
    if variant.target == "INSTRUCTIONS":
        return _replace_once(INSTRUCTIONS, variant.old, variant.new), {}
    tool_name = variant.target.removeprefix("docstring:")
    base = tool_descriptions(course_agent)[tool_name]
    return INSTRUCTIONS, {tool_name: _replace_once(base, variant.old, variant.new)}


def build_variant_agent(variant: Variant) -> Agent:
    instructions, descriptions = variant_texts(variant)
    target = Agent(instructions=instructions, output_type=[str, DeferredToolRequests])
    for func, requires_approval in TOOLS:
        target.tool_plain(
            func,
            requires_approval=requires_approval,
            description=descriptions.get(func.__name__),  # None なら docstring をそのまま使う
        )
    return target


def variant_diff(variant: Variant) -> str:
    """基準との差分（unified diff）。answer.md に貼れる形。"""
    instructions, descriptions = variant_texts(variant)
    if variant.target == "INSTRUCTIONS":
        before, after, name = INSTRUCTIONS, instructions, "app/agent.py INSTRUCTIONS"
    elif descriptions:
        tool_name, after = next(iter(descriptions.items()))
        before, name = tool_descriptions(course_agent)[tool_name], f"app/tools.py {tool_name} の docstring"
    else:
        return "（変更なし）"
    before, after = (t if t.endswith("\n") else t + "\n" for t in (before, after))
    return "".join(
        unified_diff(before.splitlines(True), after.splitlines(True), f"{name}（基準）", f"{name}（{variant.name}）")
    )


# --- 1回の実行と記録 ------------------------------------------------------------

LECTURE_REF = re.compile(r"第\s*[0-9０-９]+\s*回")
# 最後の行が「（第2回）」「関係する回：第2回」「第1回（関連回：第1回）」のような、回を示すだけの行か
LECTURE_FOOTER = re.compile(r"^[（(]?\s*((関係|関連)(する)?回\s*[:：]\s*)?第\s*[0-9０-９]+\s*回")


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip() and set(line.strip()) != {"-"}]
    return lines[-1] if lines else ""


def _quiz_answer_heads(returns: list[dict]) -> list[str]:
    """make_quiz が返した答え（定義文）の書き出し。回答に答えまで書いたかを見るのに使う。"""
    heads = []
    for r in returns:
        if r["tool"] == "make_quiz" and (m := re.search(r'"answer": "([^"]{1,20})', r["content_head"])):
            heads.append(m.group(1))
    return heads


def checks_for(question_id: str, output: str, calls: list[dict], returns: list[dict] | None = None) -> dict:
    """回答とツール呼び出しの簡単な自動チェック（目安。最終判断は回答本文を読んで行う）。"""
    names = [c["tool"] for c in calls]
    plain = output.replace("**", "")  # Markdown の太字で語が分断されないように
    result = {
        "search_calls": names.count("search_glossary"),
        "search_queries": [c["args"].get("query") for c in calls if c["tool"] == "search_glossary"],
        "summary_calls": names.count("get_lecture_summary"),
        "quiz_calls": names.count("make_quiz"),
        "save_calls": names.count("save_learning_log"),
        "lecture_footer": bool(LECTURE_FOOTER.search(_last_line(plain))),
        "lecture_ref_anywhere": bool(LECTURE_REF.search(plain)),
        "output_chars": len(output),
    }
    if question_id == "levels":
        result["has_3_levels"] = all(w in plain for w in ("基礎", "実装", "発展"))
        result["says_one_is_enough"] = bool(re.search(r"(どれか|いずれか)\s*(1|１|一)\s*つ", plain))
    if question_id == "lora":
        result["mentions_quantization"] = "量子化" in plain
    if question_id == "quiz":
        result["quiz_lecture_args"] = [c["args"].get("lecture") for c in calls if c["tool"] == "make_quiz"]
        heads = _quiz_answer_heads(returns or [])
        result["quiz_answer_shown"] = bool(heads) and any(h in plain for h in heads)
    return result


def _jsonable_args(part: ToolCallPart) -> dict:
    try:
        return part.args_as_dict()
    except Exception:  # 引数が壊れた JSON のときも記録は残す
        return {"_raw": str(part.args)}


def run_one(target: Agent, question: str, model, approve=None) -> dict:
    """1つの質問を実行し、ツール呼び出し・承認・使用量・回答・trace の文字列を返す。"""
    approvals: list[dict] = []

    def _approve(call: ToolCallPart) -> bool:
        decision = approve(call) if approve else False  # 基礎の実行では保存を頼んでいないので拒否
        approvals.append({"tool": call.tool_name, "args": _jsonable_args(call), "approved": decision})
        return decision

    buffer = io.StringIO()
    start = time.perf_counter()
    with contextlib.redirect_stdout(buffer):
        result = run_with_approval(target, question, model, approve=_approve)
        elapsed = time.perf_counter() - start
        print_trace(result)
    parts = [p for m in result.all_messages() for p in m.parts]
    calls = [{"tool": p.tool_name, "args": _jsonable_args(p)} for p in parts if isinstance(p, ToolCallPart)]
    returns = [
        {"tool": p.tool_name, "content_head": str(p.content)[:300]} for p in parts if isinstance(p, ToolReturnPart)
    ]
    usage = result.usage
    return {
        "elapsed_sec": round(elapsed, 3),
        "tool_calls": calls,
        "tool_returns": returns,
        "approvals": approvals,
        "usage": {
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
        "output": str(result.output),
        "trace": buffer.getvalue().strip(),
    }


# --- 再試行・再開 ----------------------------------------------------------------


class DailyQuotaExceeded(Exception):
    pass


def _is_daily_quota(err: ModelHTTPError) -> bool:
    body = json.dumps(err.body, ensure_ascii=False) if not isinstance(err.body, str) else err.body
    return err.status_code == 429 and ("PerDay" in body or "per day" in body.lower())


def run_with_retry(func, max_retries: int = 2):
    """429（分あたり）は60秒、503は30秒待って再実行する。日あたりの上限なら止める。"""
    attempts = []
    for attempt in range(max_retries + 1):
        try:
            return func(), attempts
        except ModelHTTPError as e:
            attempts.append({"status": e.status_code, "body": str(e.body)[:300]})
            if _is_daily_quota(e):
                raise DailyQuotaExceeded(str(e.body)[:300]) from e
            if e.status_code not in (429, 503) or attempt == max_retries:
                raise
            wait = 60 if e.status_code == 429 else 30
            print(f"    HTTP {e.status_code}。{wait}秒待って再実行します（{attempt + 1}/{max_retries}）")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def load_runs(path: Path | None = None) -> list[dict]:
    path = path or RUNS_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_key(record: dict) -> tuple:
    return (record["variant"], record["question_id"], record["rep"], record["model"])


def plan(reps: int, only: list[str] | None = None) -> list[tuple[Variant, str, int]]:
    """実行順。まず基準の各質問を1回ずつ（演習の記録）→ 変種の1回目 → 2回目以降、の順に並べる。"""
    variants = [v for v in VARIANTS if not only or v.name in only]
    items = []
    for rep in range(1, reps + 1):
        for v in sorted(variants, key=lambda v: v is not BASELINE):
            items += [(v, q, rep) for q in v.questions]
    return items


# --- 実装（本物の CLI に y / n を入力する） ---------------------------------------


def run_cli_save(answer: str, out_path: Path) -> dict:
    log_dir = tools.LEARNING_LOG_DIR
    before = set(log_dir.glob("*.md")) if log_dir.exists() else set()
    command = [sys.executable, "-m", "app.agent", "--trace", SAVE_QUESTION]
    started = datetime.now(JST)
    busy = []  # 503・429 で失敗したら待って再実行する（基礎の実行と同じ方針）
    for attempt in range(3):
        proc = subprocess.run(
            command, input=f"{answer}\n", capture_output=True, text=True, cwd=ROOT, timeout=300, env=os.environ.copy()
        )
        status = next((s for s in ("503", "429") if proc.returncode != 0 and f"（{s}）" in proc.stdout), None)
        if status is None and not (proc.returncode != 0 and "レート制限" in proc.stdout):
            break
        busy.append(status or "429")
        if attempt < 2:
            wait = 30 if status == "503" else 60
            print(f"    HTTP {busy[-1]}。{wait}秒待って再実行します（{attempt + 1}/2）")
            time.sleep(wait)
    after = set(log_dir.glob("*.md")) if log_dir.exists() else set()
    new_files = sorted(after - before)
    lines = [
        f"# 実行日時: {started.isoformat(timespec='seconds')}",
        f"# コマンド: uv run python -m app.agent --trace \"{SAVE_QUESTION}\"",
        f"# 確認への入力: {answer!r}",
        f"# 終了コード: {proc.returncode}",
        f"# 混雑による再実行: {len(busy)}回 {busy if busy else ''}".rstrip(),
        "",
        proc.stdout.rstrip(),
    ]
    if proc.stderr.strip():
        lines += ["", "# --- stderr ---", proc.stderr.rstrip()[-2000:]]
    lines += ["", f"# learning_log/ に増えたファイル: {[p.name for p in new_files] or 'なし'}"]
    for p in new_files:
        lines += [f"# --- {p.name} ---", p.read_text(encoding="utf-8").rstrip()]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"answer": answer, "returncode": proc.returncode, "new_files": [p.name for p in new_files]}


# --- 要約 ---------------------------------------------------------------------------


def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _mean(values: list) -> str:
    values = [v for v in values if v is not None]
    return f"{sum(values) / len(values):.2f}" if values else "-"


def _rate(values: list[bool]) -> str:
    return f"{sum(values)}/{len(values)}" if values else "-"


def summarize(records: list[dict]) -> str:
    ok = [r for r in records if r.get("ok")]
    failed = [r for r in records if not r.get("ok")]
    lines = [
        "# 第3回 基礎：INSTRUCTIONS / docstring の比較（自動集計）",
        "",
        f"- 集計日時: {datetime.now(JST).isoformat(timespec='seconds')}",
        f"- 成功した実行: {len(ok)} 件、失敗: {len(failed)} 件",
        f"- モデル: {', '.join(sorted({r['model'] for r in records})) or '-'}",
        "- 数値は成功した実行の平均。自動チェックは目安で、最終判断は day3_runs.jsonl の回答本文で行う",
        f"- 混雑（503）・レート制限（429）で再実行した回数: {sum(len(r.get('retries', [])) for r in ok)}",
        "- 「最終行が第N回」は、最後の行が「（第2回）」「関係する回：第2回」のように回だけを示す行かどうか",
        "",
        "| 変種 | 質問 | 成功/試行 | search回数 | requests | 入力tok | 出力tok | 最終行が第N回 | 本文に第N回 | その他 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for v in VARIANTS:
        for q in v.questions:
            group = [r for r in records if r["variant"] == v.name and r["question_id"] == q]
            if not group:
                continue
            good = [r for r in group if r.get("ok")]
            for r in good:  # チェックの改善が過去の記録にも反映されるよう、回答本文から計算し直す
                r["checks"] = checks_for(q, r["output"], r["tool_calls"], r.get("tool_returns"))
            extra = []
            if q == "levels":
                extra.append(f"3レベル {_rate([r['checks']['has_3_levels'] for r in good])}")
                extra.append(f"どれか1つ {_rate([r['checks']['says_one_is_enough'] for r in good])}")
            if q == "lora":
                extra.append(f"量子化 {_rate([r['checks']['mentions_quantization'] for r in good])}")
                queries = [r["checks"]["search_queries"] for r in good]
                extra.append("query " + " / ".join(json.dumps(x, ensure_ascii=False) for x in queries))
            if q == "quiz":
                extra.append(f"make_quiz呼出 {_rate([r['checks']['quiz_calls'] > 0 for r in good])}")
                extra.append(f"summary呼出 {_rate([r['checks']['summary_calls'] > 0 for r in good])}")
                extra.append(f"答えまで表示 {_rate([r['checks']['quiz_answer_shown'] for r in good])}")
            saves = sum(r["checks"]["save_calls"] for r in good)
            if saves:
                extra.append(f"save_learning_log {saves}回（拒否済み）")
            lines.append(
                f"| {v.name} | {q} | {len(good)}/{len(group)} "
                f"| {_mean([r['checks']['search_calls'] for r in good])} "
                f"| {_mean([r['usage']['requests'] for r in good])} "
                f"| {_mean([r['usage']['input_tokens'] for r in good])} "
                f"| {_mean([r['usage']['output_tokens'] for r in good])} "
                f"| {_rate([r['checks']['lecture_footer'] for r in good])} "
                f"| {_rate([r['checks']['lecture_ref_anywhere'] for r in good])} "
                f"| {'; '.join(extra)} |"
            )
    lines += ["", "## 変種の説明", ""]
    lines += [f"- `{v.name}`（{v.target}）: {v.label}" for v in VARIANTS]
    if failed:
        lines += ["", "## 失敗した実行", ""]
        lines += [f"- {r['variant']} / {r['question_id']} / rep{r['rep']}: {r.get('error')}" for r in failed]
    return "\n".join(lines) + "\n"


def write_static_files() -> None:
    """APIキー不要のもの: 変種の差分、ツール一覧、テスト結果、環境。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    diffs = ["# 第3回 基礎：比較した変種と、基準との差分", ""]
    for v in VARIANTS:
        diffs += [f"## {v.name}", "", f"{v.label}（変更箇所: {v.target}、質問: {', '.join(v.questions)}）", ""]
        diffs += ["```diff", variant_diff(v).rstrip(), "```", ""]
    (RESULTS_DIR / "variants.md").write_text("\n".join(diffs), encoding="utf-8")

    def _capture(module_args: list[str]) -> str:
        proc = subprocess.run([sys.executable, "-m", *module_args], capture_output=True, text=True, cwd=ROOT)
        shown = "pytest -q" if module_args[0] == "pytest" else "python -m " + " ".join(module_args)
        return f"$ uv run {shown}\n{proc.stdout}{proc.stderr}"

    (RESULTS_DIR / "list_tools.txt").write_text(_capture(["app.agent", "--list-tools"]), encoding="utf-8")
    (RESULTS_DIR / "pytest.txt").write_text(_capture(["pytest", "-q"]), encoding="utf-8")
    env = {
        "date_jst": datetime.now(JST).isoformat(timespec="seconds"),
        "model": MODEL,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "codespaces": os.getenv("CODESPACES") == "true",
        "pydantic-ai-slim": metadata.version("pydantic-ai-slim"),
        "google-genai": metadata.version("google-genai"),
    }
    (RESULTS_DIR / "environment.json").write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="第3回 演習・宿題（基礎・実装）を実行して記録する")
    parser.add_argument("--reps", type=int, default=3, help="各条件の繰り返し回数（既定3）")
    parser.add_argument("--only", nargs="*", help="実行する変種名（省略時は全部）")
    parser.add_argument("--sleep", type=float, default=10.0, help="実行と実行の間に待つ秒数（既定10）")
    parser.add_argument("--skip-cli", action="store_true", help="実装（CLI の y/n）を実行しない")
    parser.add_argument("--dry-run", action="store_true", help="実行内容と差分を表示して終了（APIキー不要）")
    parser.add_argument("--summarize", action="store_true", help="保存済みの結果から要約だけを作り直す")
    args = parser.parse_args()

    items = plan(args.reps, args.only)
    if args.dry_run:
        for v in VARIANTS:
            print(f"== {v.name}: {v.label}\n{variant_diff(v)}")
        print(f"基礎の実行: {len(items)} 回（各回で LLM を2〜4回呼ぶ）。実装: CLI を2回（y と n）")
        return
    if args.summarize:
        (RESULTS_DIR / "summary.md").write_text(summarize(load_runs()), encoding="utf-8")
        print(f"要約を書きました: {_shown(RESULTS_DIR / 'summary.md')}")
        return

    from app.agent import build_model  # ここで初めて API キーを読む

    write_static_files()
    model = build_model()
    done = {run_key(r) for r in load_runs() if r.get("ok")}
    agents = {}
    print(f"[model] {MODEL}  結果: {_shown(RESULTS_DIR)}/")

    def _basic(variant: Variant, question_id: str, rep: int) -> None:
        record = {"variant": variant.name, "question_id": question_id, "rep": rep, "model": MODEL}
        if run_key(record) in done:
            return
        target = agents.setdefault(variant.name, build_variant_agent(variant))
        record |= {
            "experiment": "basic",
            "changed": variant.target,
            "question": QUESTIONS[question_id],
            "started_at": datetime.now(JST).isoformat(timespec="seconds"),
        }
        print(f"- {variant.name} / {question_id} / rep{rep}", flush=True)
        try:
            data, attempts = run_with_retry(lambda: run_one(target, QUESTIONS[question_id], model))
            record |= {"ok": True, "retries": attempts, **data}
            record["checks"] = checks_for(question_id, data["output"], data["tool_calls"], data["tool_returns"])
            print(f"    tools={[c['tool'] for c in data['tool_calls']]} requests={data['usage']['requests']}")
        except DailyQuotaExceeded:
            raise
        except Exception as e:  # 失敗も記録に残す
            status = getattr(e, "status_code", None)
            record |= {"ok": False, "error": {"type": type(e).__name__, "status": status, "message": str(e)[:300]}}
            print(f"    失敗: {type(e).__name__} {status or ''}")
        with RUNS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        time.sleep(args.sleep)

    try:
        first = [it for it in items if it[0] is BASELINE and it[2] == 1]
        for item in first:
            _basic(*item)
        if not args.skip_cli:
            for answer, name in (("y", "cli_save_approve.txt"), ("n", "cli_save_deny.txt")):
                done_before = RESULTS_DIR / name
                if done_before.exists() and "# 終了コード: 0" in done_before.read_text(encoding="utf-8"):
                    continue
                print(f"- 実装: CLI に {answer!r} を入力")
                info = run_cli_save(answer, RESULTS_DIR / name)
                print(f"    終了コード={info['returncode']} 増えたファイル={info['new_files']}")
                time.sleep(args.sleep)
        for item in items:
            if item not in first:
                _basic(*item)
    except DailyQuotaExceeded as e:
        print(f"\n1日あたりの上限に達したので止めます。翌日に同じコマンドで続きから実行できます。\n{e}")
    finally:
        (RESULTS_DIR / "summary.md").write_text(summarize(load_runs()), encoding="utf-8")
        print(f"\n要約: {_shown(RESULTS_DIR / 'summary.md')}")


if __name__ == "__main__":
    main()
