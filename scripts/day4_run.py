"""第4回 演習・宿題（基礎・実装）の採点をまとめて実行し、結果を lectures/04/results/ に保存する。

使い方（Codespaces で、リポジトリの直下から）:
    uv run --frozen python -m scripts.day4_run generate   # ① 自分の評価セット 10 件に、自分のエージェントで回答を付ける
    （tools/annotate.py で、演習の 10 件と自分の 10 件にラベルを付ける）
    uv run --frozen python -m scripts.day4_run            # ② 全条件を採点して要約を書く（5 分前後）
    uv run --frozen python -m scripts.day4_run --summarize  # 保存済みの結果から要約だけ作り直す（API キー不要）
    uv run --frozen python -m scripts.day4_run --model test # API を呼ばない偽モデルで流れだけ確かめる（別フォルダに保存）

条件（どれも app/judge.py の採点と集計をそのまま使う）:
    ex_before    演習 STEP 2: 配布時の rubric（「まだ決めていないこと」あり）
    baseline     演習 STEP 3: 方針を 1 行書き足した rubric（＝宿題の基準になる条件）
    baseline_2   baseline をもう一度実行（何も変えなくても判定が動くかを見る）
    hw_model     宿題（基礎）: 採点のモデルだけを変える
    hw_rubric    宿題（基礎）: 「分かりやすさ」の文言だけを変える
    hw_order     宿題（基礎）: 判定の順序だけを変える（判定を先、理由を後）
    my_cases     宿題（実装）: 自分の評価セット 10 件を baseline と同じ設定で採点する

途中で止まっても、もう一度実行すれば終わった条件は飛ばして続きから実行する。
"""

import argparse
import contextlib
import io
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

from app import judge
from app.config import MODEL

ROOT = judge.ROOT
L4 = ROOT / "lectures" / "04"
RESULTS_DIR = L4 / "results"
RUBRIC_V0 = L4 / "rubrics" / "rubric_v0_original.md"
RUBRIC_CLARITY = L4 / "rubrics" / "rubric_hw_clarity.md"
MY_CASES = ROOT / "data" / "eval" / "my_cases.jsonl"
MY_LABELS = L4 / "my_labels.jsonl"
INSTRUCTOR_LABELS = L4 / "reference" / "labels_instructor.jsonl"
JST = timezone(timedelta(hours=9))

HW_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]  # 上から試し、使えなければ次へ
REASON_FIRST_LINE = "- 理由は日本語で 1〜2 文。先に理由を書いてから判定を決める"
VERDICT_FIRST_LINE = "- 先に判定を決めてから、その理由を日本語で 1〜2 文で書く"

# (名前, 評価セット, ラベル, rubric, モデル, 順序, 説明)
CONDITIONS = [
    ("ex_before", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, RUBRIC_V0, "default", "reason_first", "演習 STEP 2：配布時の rubric"),
    ("baseline", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, judge.DEFAULT_RUBRIC, "default", "reason_first", "演習 STEP 3：方針を書き足した rubric（基準）"),
    ("baseline_2", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, judge.DEFAULT_RUBRIC, "default", "reason_first", "基準をもう一度（何も変えない）"),
    ("hw_model", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, judge.DEFAULT_RUBRIC, "hw", "reason_first", "基礎：採点のモデルだけを変える"),
    ("hw_rubric", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, RUBRIC_CLARITY, "default", "reason_first", "基礎：「分かりやすさ」の文言だけを変える"),
    ("hw_order", judge.DEFAULT_CASES, judge.DEFAULT_LABELS, judge.DEFAULT_RUBRIC, "default", "verdict_first", "基礎：判定を先、理由を後にする"),
    ("my_cases", MY_CASES, MY_LABELS, judge.DEFAULT_RUBRIC, "default", "reason_first", "実装：自分の評価セット 10 件"),
]


# --- 判定の順序を入れ替えた出力の型（宿題・基礎）。app/judge.py の型は書き換えない -------------


class VerdictFirst(BaseModel):
    """CriterionVerdict の項目の順だけを入れ替えたもの（判定→理由）。"""

    verdict: judge.Verdict = Field(description="pass / fail / unsure のどれか")
    reason: str = Field(description="判定の理由。日本語で 1〜2 文")


class JudgeResultVerdictFirst(BaseModel):
    grounding: VerdictFirst = Field(description=judge.JudgeResult.model_fields["grounding"].description)
    scope: VerdictFirst = Field(description=judge.JudgeResult.model_fields["scope"].description)
    hint: VerdictFirst = Field(description=judge.JudgeResult.model_fields["hint"].description)
    clarity: VerdictFirst = Field(description=judge.JudgeResult.model_fields["clarity"].description)


def build_judge_for(model, rubric: str, order: str) -> Agent:
    """順序が reason_first なら講座の build_judge をそのまま使う。verdict_first なら順序に関わる 3 か所だけ変える。"""
    if order == "reason_first":
        return judge.build_judge(model, rubric)
    if rubric.count(REASON_FIRST_LINE) != 1:
        raise ValueError("rubric に「先に理由を書いてから判定を決める」の行が見つかりません")
    instructions = rubric.replace(REASON_FIRST_LINE, VERDICT_FIRST_LINE) + (
        "\n\n# 出力の形式\n"
        "4 つの基準（grounding, scope, hint, clarity）それぞれについて、verdict を pass / fail / unsure のどれかに先に決め、"
        "そのあとで reason（理由）を書いてください。"
    )
    return Agent(model, output_type=JudgeResultVerdictFirst, instructions=instructions, model_settings={"temperature": 0.0})


# --- 実行 -------------------------------------------------------------------------


class DailyQuotaExceeded(Exception):
    pass


def with_retry(func, max_retries: int = 3):
    """429（分あたり）は 60 秒、503 は 30 秒待って再実行する。再実行した回数も返す。"""
    retries = []
    for attempt in range(max_retries + 1):
        try:
            return func(), retries
        except ModelHTTPError as e:
            body = str(e.body)
            retries.append(e.status_code)
            if e.status_code == 429 and ("PerDay" in body or "per day" in body.lower()):
                raise DailyQuotaExceeded(body[:300]) from e
            if e.status_code not in (429, 503) or attempt == max_retries:
                raise
            wait = 60 if e.status_code == 429 else 30
            print(f"\n    HTTP {e.status_code}。{wait} 秒待って再実行します（{attempt + 1}/{max_retries}）", flush=True)
            time.sleep(wait)
        except UnexpectedModelBehavior:
            retries.append("format")
            if attempt == max_retries:
                raise
            print("\n    判定の形式が崩れたので再実行します", flush=True)
    raise RuntimeError("unreachable")


def judge_one_by_one(agent: Agent, cases: list[dict], wait: float) -> tuple[dict, list]:
    """judge.judge_cases を 1 件ずつ呼ぶ（途中で 429/503 になっても、その 1 件だけをやり直せるように）。"""
    verdicts, all_retries = {}, []
    print(f"    採点中 {len(cases)} 件 ", end="", flush=True)
    for case in cases:
        def one(c=case):
            with contextlib.redirect_stdout(io.StringIO()):  # judge_cases 自身の進み具合の表示は出さない
                return judge.judge_cases(agent, [c])

        got, retries = with_retry(one)
        verdicts.update(got)
        all_retries += retries
        print(".", end="", flush=True)
        time.sleep(wait)
    print()
    return verdicts, all_retries


def build_model(name: str):
    return judge.build_test_model() if name == "test" else judge.build_llm_model(name)


def run_condition(cond, default_model: str, wait: float, out_dir: Path) -> dict | None:
    name, cases_path, labels_path, rubric_path, model_kind, order, label = cond
    out_path = out_dir / f"{name}.json"
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    if not labels_path.exists():
        print(f"- {name}: {judge._rel(labels_path)} がまだ無いので飛ばします（tools/annotate.py でラベルを付けてください）")
        return None
    cases = judge.read_jsonl(cases_path)
    if any(not c.get("answer") for c in cases):
        print(f"- {name}: {judge._rel(cases_path)} に回答が無い質問があるので飛ばします（先に generate を実行してください）")
        return None
    labels, rubric = judge.load_labels(labels_path), rubric_path.read_text(encoding="utf-8")
    candidates = [default_model] if model_kind == "default" or default_model == "test" else HW_MODELS
    skipped = []
    for model_name in candidates:
        print(f"- {name}（{label}）  model={model_name}", flush=True)
        agent = build_judge_for(build_model(model_name), rubric, order)
        started = time.perf_counter()
        try:
            verdicts, retries = judge_one_by_one(agent, cases, wait)
        except DailyQuotaExceeded:
            if model_kind == "default":
                raise
            skipped.append({"model": model_name, "reason": "1日あたりの上限"})
            continue
        except ModelHTTPError as e:
            if model_kind == "default":
                raise
            skipped.append({"model": model_name, "reason": f"HTTP {e.status_code}"})
            print(f"    {model_name} は使えませんでした（HTTP {e.status_code}）。次の候補を試します")
            continue
        record = {
            "condition": name, "label": label, "model": model_name, "order": order,
            "cases": str(judge._rel(cases_path)), "labels": str(judge._rel(labels_path)), "rubric": str(judge._rel(rubric_path)),
            "run_at": datetime.now(JST).isoformat(timespec="seconds"), "elapsed_sec": round(time.perf_counter() - started, 1),
            "retries": retries, "skipped_models": skipped,
            "verdicts": verdicts, "summary": judge.summarize(cases, verdicts, labels),
        }
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        judge.print_summary(record["summary"])
        return record
    print(f"    {name}: 使えるモデルがありませんでした {skipped}")
    return None


# --- 要約 ---------------------------------------------------------------------------


def fail_recall(record: dict, labels: dict) -> tuple[int, int]:
    """人が不合格にした項目（LLM が判定する 4 基準）のうち、LLM も不合格にした数。unsure は見抜けなかった側に数える。"""
    caught = total = 0
    for cid, v in record["verdicts"].items():
        for key, _ in judge.LLM_CRITERIA:
            if labels.get(cid, {}).get(key) == "fail":
                total += 1
                caught += int(v[key]["verdict"] == "fail")
    return caught, total


def flips(base: dict, other: dict) -> list[str]:
    """基準の条件と比べて、LLM の判定が変わった項目。"""
    out = []
    for cid, v in other["verdicts"].items():
        for key, name in judge.LLM_CRITERIA:
            a, b = base["verdicts"][cid][key]["verdict"], v[key]["verdict"]
            if a != b:
                out.append(f"#{cid} {name}: {a} → {b}（理由: {v[key]['reason']}）")
    return out


def code_checks(case: dict) -> dict:
    """自分の評価セット向けの、コードで決まる確認（LLM に聞かない）。"""
    called = [c["tool"] for c in case.get("tool_calls", [])]
    wants_glossary = bool(case.get("reference", {}).get("glossary"))
    return {
        "lecture_mark": judge.check_lecture_mark(case["answer"]),
        "tools": called,
        "searched_when_expected": (("search_glossary" in called) if wants_glossary else None),
        "has_code_block": "```" in case["answer"],
        "chars": len(case["answer"]),
    }


def _labels_or_empty(path: Path) -> dict:
    return judge.load_labels(path) if path.exists() else {}


def summarize(out_dir: Path) -> str:
    records = {c[0]: json.loads((out_dir / f"{c[0]}.json").read_text(encoding="utf-8"))
               for c in CONDITIONS if (out_dir / f"{c[0]}.json").exists()}
    lines = ["# 第4回 演習・宿題：採点結果の要約（自動集計）", "",
             f"- 集計日時: {datetime.now(JST).isoformat(timespec='seconds')}",
             "- 「一致」は自分のラベルと LLM の判定が同じだった件数／比べた件数（LLM が unsure にした項目は分母から外れる）",
             "- 「不合格の再現」は、自分が不合格にした項目のうち LLM も不合格にした数（LLM が判定する 4 基準の合計）",
             "- 10 件の評価セットなので、1 件の違いが 10 ポイントの違いになる。数字は傾向として読む", ""]
    head = "| 条件 | モデル | 根拠 | 範囲 | ヒント | 分かりやすさ | 回の表示（コード） | 要確認 | 総合 | 不合格の再現 | 再実行 |"
    lines += ["## 条件ごとの一致", "", head, "|---|---|---|---|---|---|---|---:|---|---|---:|"]
    for name, rec in records.items():
        s = rec["summary"]
        per = [f"{s['per_criterion'][k]['agree']}/{s['per_criterion'][k]['compared']}" for k, _ in judge.ALL_CRITERIA]
        caught, total = fail_recall(rec, _labels_or_empty(ROOT / rec["labels"]))
        lines.append(f"| {name}（{rec['label']}） | {rec['model']} | " + " | ".join(per) +
                     f" | {len(s['review'])} | {s['overall']['agree']}/{s['overall']['compared']} | {caught}/{total} | {len(rec['retries'])} |")

    base = records.get("baseline")
    if base:
        lines += ["", "## 基準（baseline）から LLM の判定が変わった項目", ""]
        for name in ("ex_before", "baseline_2", "hw_model", "hw_rubric", "hw_order"):
            if name in records:
                changed = flips(base, records[name])
                lines.append(f"- **{name}**：{len(changed)} 項目" + ("" if changed else "（変化なし）"))
                lines += [f"  - {c}" for c in changed]

    for name, rec in records.items():
        s = rec["summary"]
        if s["review"] or s["mismatches"]:
            lines += ["", f"## {name}：要確認と不一致", ""]
            lines += [f"- 要確認 #{r['id']} {r['name']}: {r['reason']}" for r in s["review"]]
            lines += [f"- 不一致 #{m['id']} {m['name']} {m['kind']}（LLM={m['judge']} 自分={m['human']}）: {m['reason']}" for m in s["mismatches"]]

    mine = _labels_or_empty(judge.DEFAULT_LABELS)
    if mine and INSTRUCTOR_LABELS.exists():
        ref = judge.load_labels(INSTRUCTOR_LABELS)
        lines += ["", "## 自分のラベルと講師のラベル（演習の 10 件）", ""]
        for key, kname in judge.ALL_CRITERIA:
            diff = [cid for cid in mine if cid in ref and mine[cid].get(key) != ref[cid].get(key)]
            lines.append(f"- {kname}: {len(mine) - len(diff)}/{len(mine)} 一致" + (f"（違う項目: {', '.join('#' + d for d in diff)}）" if diff else ""))
        flagged = [cid for cid, row in mine.items() if row.get("unsure_flag")]
        lines.append(f"- 自分が「迷った」を付けた項目: {', '.join('#' + c for c in flagged) or 'なし'}")

    if MY_CASES.exists():
        cases = judge.read_jsonl(MY_CASES)
        if all(c.get("answer") for c in cases):
            my_labels = _labels_or_empty(MY_LABELS)
            lines += ["", "## 自分の評価セット：コードで決まる確認", "",
                      "| id | 種類 | 呼ばれたツール | 回の表示（コード） | 回の表示（自分） | 用語集を検索したか | コードブロック | 文字数 |",
                      "|---|---|---|---|---|---|---|---:|"]
            for c in cases:
                k = code_checks(c)
                searched = {True: "した", False: "しなかった", None: "—"}[k["searched_when_expected"]]
                lines.append(f"| {c['id']} | {c.get('category', '')} | {', '.join(k['tools']) or 'なし'} | {k['lecture_mark']} "
                             f"| {my_labels.get(c['id'], {}).get('lecture_mark', '—')} | {searched} | {'あり' if k['has_code_block'] else 'なし'} | {k['chars']} |")
    return "\n".join(lines) + "\n"


def write_static(out_dir: Path) -> None:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True, cwd=ROOT)
    (out_dir / "pytest.txt").write_text(f"$ uv run pytest -q\n{proc.stdout}{proc.stderr}", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="第4回 演習・宿題の採点をまとめて実行する")
    parser.add_argument("command", nargs="?", choices=["generate"], help="generate: 自分の評価セットに回答を付ける")
    parser.add_argument("--model", default=None, help="既定は AIE_MODEL。'test' で API を呼ばない偽モデル")
    parser.add_argument("--wait", type=float, default=3.0, help="1 件ごとに待つ秒数（既定 3）")
    parser.add_argument("--force", action="store_true", help="generate: 回答があっても作り直す")
    parser.add_argument("--summarize", action="store_true", help="保存済みの結果から要約だけを作り直す")
    args = parser.parse_args(argv)
    model_name = args.model or MODEL
    out_dir = RESULTS_DIR if model_name != "test" else L4 / "results_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "generate":
        cases = judge.read_jsonl(MY_CASES)
        if all(c.get("answer") for c in cases) and not args.force:
            print(f"{judge._rel(MY_CASES)} には回答がもう付いています（作り直すなら --force）")
            return
        from app.agent import agent, build_model as build_agent_model

        print(f"[model] {MODEL}  自分のエージェント（app/agent.py）で {len(cases)} 件の回答を生成します")
        done = []
        for case in cases:  # 1 件ずつ生成し、429/503 ならその 1 件だけやり直す
            got, _ = with_retry(lambda c=case: judge.generate_with(agent, build_agent_model(), [c]))
            done += got
            time.sleep(args.wait)
        judge.write_jsonl(MY_CASES, done)
        print(f"→ {judge._rel(MY_CASES)} に回答を書き込みました。次に tools/annotate.py でラベルを付けてください")
        return

    if not args.summarize:
        print(f"[model] {model_name}  結果: {judge._rel(out_dir)}/")
        try:
            for cond in CONDITIONS:
                run_condition(cond, model_name, args.wait if model_name != "test" else 0.0, out_dir)
        except DailyQuotaExceeded as e:
            print(f"\n1日あたりの上限に達したので止めます。翌日に同じコマンドで続きから実行できます。\n{e}")
        except ModelHTTPError as e:
            print(f"\nAPI エラーで止まりました（HTTP {e.status_code}）。少し待って同じコマンドを実行すると続きから動きます")
        if model_name != "test":
            write_static(out_dir)
    (out_dir / "summary.md").write_text(summarize(out_dir), encoding="utf-8")
    print(f"\n要約: {judge._rel(out_dir / 'summary.md')}")


if __name__ == "__main__":
    main()
