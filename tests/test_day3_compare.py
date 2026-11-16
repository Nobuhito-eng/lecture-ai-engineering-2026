"""scripts/day3_compare.py のテスト（LLM も API キーも使わない）。

比較が公平であること（基準は本物のエージェントと同じ・変種は1か所だけ違う）を確かめる。
"""

import json

from pydantic_ai.models.test import TestModel

from app.agent import agent as course_agent
from scripts import day3_compare as d3


def _request_view(target):
    """モデルに渡る指示とツール定義（名前・説明文・引数・承認の要否）を取り出す。"""
    model = TestModel(call_tools=[])
    result = target.run_sync("ツール一覧", model=model)
    tools = {
        t.name: (t.description, json.dumps(t.parameters_json_schema, sort_keys=True), t.kind)
        for t in model.last_model_request_parameters.function_tools
    }
    return result.all_messages()[0].instructions, tools


def test_baseline_is_identical_to_the_course_agent():
    assert _request_view(d3.build_variant_agent(d3.BASELINE)) == _request_view(course_agent)


def test_each_variant_changes_exactly_one_place():
    base_instructions, base_tools = _request_view(course_agent)
    for v in d3.VARIANTS:
        if v is d3.BASELINE:
            continue
        instructions, tools = _request_view(d3.build_variant_agent(v))
        if v.target == "INSTRUCTIONS":
            assert tools == base_tools, v.name
            assert instructions != base_instructions, v.name
            assert v.old in base_instructions and v.old not in instructions, v.name
        else:
            assert instructions == base_instructions, v.name
            changed = [name for name in base_tools if tools[name] != base_tools[name]]
            assert changed == [v.target.removeprefix("docstring:")], v.name
            assert v.new in tools[changed[0]][0], v.name


def test_plan_runs_baseline_first_and_balances_reps():
    items = d3.plan(reps=2)
    assert [(v.name, q, rep) for v, q, rep in items[:3]] == [
        ("baseline", "levels", 1), ("baseline", "lora", 1), ("baseline", "quiz", 1)
    ]
    assert max(rep for *_, rep in items[: len(items) // 2]) == 1  # 1回目を全部終えてから2回目
    assert len(items) == 2 * sum(len(v.questions) for v in d3.VARIANTS)


def test_checks_detect_lecture_reference_and_levels():
    output = "基礎・実装・発展の3つで、どれか**1つ**に取り組めば完了です。\n\n---\n関係する回：第1回"
    calls = [{"tool": "search_glossary", "args": {"query": "3レベル"}}]
    c = d3.checks_for("levels", output, calls)
    assert c["search_calls"] == 1 and c["search_queries"] == ["3レベル"]
    assert c["lecture_footer"] and c["has_3_levels"] and c["says_one_is_enough"]
    for footer in ["（第2回）", "第1回（関連回：第1回）", "（関連する回：第1回）", "第2回"]:
        assert d3.checks_for("lora", f"本文\n\n{footer}", [])["lecture_footer"], footer
    # 本文の中で回に触れているだけなら「最終行が第N回」には数えない
    woven = d3.checks_for("lora", "本文\n\nどちらも第2回で扱う内容です。", [])
    assert woven["lecture_ref_anywhere"] and not woven["lecture_footer"]
    assert not d3.checks_for("levels", "基礎と実装があります。", [])["lecture_footer"]


def test_checks_detect_whether_quiz_answer_is_shown():
    returns = [{"tool": "make_quiz", "content_head": '{"lecture": 2, "question": "「PEFT」の意味は？", '
                '"answer": "モデルの全パラメータではなく、ごく一部"}'}]
    calls = [{"tool": "make_quiz", "args": {"lecture": 2}}]
    assert not d3.checks_for("quiz", "「PEFT」の意味は？考えてみてください。", calls, returns)["quiz_answer_shown"]
    shown = "問題：「PEFT」の意味は？\n答え：モデルの全パラメータではなく、ごく一部だけを学習する手法"
    assert d3.checks_for("quiz", shown, calls, returns)["quiz_answer_shown"]


def test_run_one_records_calls_usage_and_denies_unrequested_save():
    target = d3.build_variant_agent(d3.BASELINE)
    record = d3.run_one(target, "LoRAとは？", TestModel())  # TestModel は全ツールを呼ぶ
    names = [c["tool"] for c in record["tool_calls"]]
    assert {"search_glossary", "make_quiz", "save_learning_log"} <= set(names)
    assert record["approvals"] == [
        {"tool": "save_learning_log", "args": record["approvals"][0]["args"], "approved": False}
    ]
    assert record["usage"]["requests"] == 2
    assert "--- trace ---" in record["trace"] and "[approval]" in record["trace"]


def test_main_end_to_end_with_fake_model(tmp_path, monkeypatch):
    """API の代わりに TestModel で main を最後まで動かし、記録と要約ができることを確かめる。"""
    import app.agent

    monkeypatch.setattr(d3, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(d3, "RUNS_FILE", tmp_path / "day3_runs.jsonl")
    monkeypatch.setattr(d3, "write_static_files", lambda: None)
    monkeypatch.setattr(app.agent, "build_model", lambda: TestModel(call_tools=["search_glossary"]))
    monkeypatch.setattr("sys.argv", ["day3_compare", "--reps", "1", "--sleep", "0", "--skip-cli"])
    d3.main()
    runs = d3.load_runs(tmp_path / "day3_runs.jsonl")
    assert len(runs) == len(d3.plan(1)) and all(r["ok"] for r in runs)

    # もう一度実行しても、成功済みの組み合わせは飛ばす（再開できる）
    d3.main()
    assert len(d3.load_runs(tmp_path / "day3_runs.jsonl")) == len(runs)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| baseline | levels | 1/1 |" in summary
