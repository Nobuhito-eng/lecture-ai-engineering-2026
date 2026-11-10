"""scripts/day4_run.py と、第4回で app/judge.py・評価セットに足した部分のテスト（API キーは使わない）。"""

import json
import shutil

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from app import judge
from app.agent import DENIED_MESSAGE, agent
from scripts import day4_run as d4


def test_my_cases_are_well_formed():
    cases = judge.read_jsonl(d4.MY_CASES)
    glossary_ids = {e["id"] for e in judge.tools.load_glossary()}
    exercise_ids = {c["id"] for c in judge.read_jsonl(judge.DEFAULT_CASES)}
    assert len(cases) == 10 and len({c["id"] for c in cases}) == 10
    assert not {c["id"] for c in cases} & exercise_ids  # ラベル付けの画面で、演習の入力欄と混ざらないように
    assert len({c["category"] for c in cases}) >= 8  # 正常系だけでなく、種類を分けてある
    for c in cases:
        assert c["question"] and c["reference"]["expected"]
        assert set(c["reference"]["glossary"]) <= glossary_ids


def test_rubric_variants_differ_in_one_place():
    def changed(a, b):
        la, lb = a.read_text(encoding="utf-8").splitlines(), b.read_text(encoding="utf-8").splitlines()
        return [(x, y) for x, y in zip(la, lb) if x != y], len(la) - len(lb)

    lines, extra = changed(judge.DEFAULT_RUBRIC, d4.RUBRIC_CLARITY)
    assert extra == 0 and len(lines) == 1 and "簡潔" in lines[0][1]  # 宿題（基礎）: 1 行だけ違う
    rubric = judge.DEFAULT_RUBRIC.read_text(encoding="utf-8")
    assert rubric.count(d4.REASON_FIRST_LINE) == 1
    assert "推測で断定したことにあたる（fail）" in rubric  # 演習 STEP 3 で書き足した方針（自分のラベルに合わせて fail）
    assert "一般的な説明をすることが" in d4.RUBRIC_V0.read_text(encoding="utf-8")  # 配布時は「まだ決めていない」


def test_verdict_first_changes_only_the_order():
    rubric = judge.DEFAULT_RUBRIC.read_text(encoding="utf-8")
    seen = {}
    for order in ("reason_first", "verdict_first"):
        model = TestModel()
        d4.build_judge_for(model, rubric, order).run_sync("x")
        tool = model.last_model_request_parameters.output_tools[0]
        schema = json.dumps(tool.parameters_json_schema, ensure_ascii=False)
        seen[order] = (schema.index('"reason"') < schema.index('"verdict"'), set(tool.parameters_json_schema["properties"]))
    assert seen["reason_first"][0] and not seen["verdict_first"][0]  # モデルに渡る型で、項目の順が入れ替わっている
    assert seen["reason_first"][1] == seen["verdict_first"][1] == {"grounding", "scope", "hint", "clarity"}


def test_generate_denies_save_and_records_tool_calls(isolated_learning_log):
    def scripted(messages, info):
        last = messages[-1].parts[-1]
        if isinstance(last, ToolReturnPart):
            return ModelResponse(parts=[TextPart(f"保存していません。\n\n関係する回：第2回（{last.content[:8]}）")])
        return ModelResponse(parts=[ToolCallPart("save_learning_log", {"title": "t", "content": "c"})])

    cases = judge.generate_with(agent, FunctionModel(scripted), [{"id": "m07", "question": "学習ログに保存して", "answer": ""}])
    assert cases[0]["answer"].startswith("保存していません")  # 承認待ちの入れ物ではなく、文章の回答になる
    assert DENIED_MESSAGE[:8] in cases[0]["answer"]  # 拒否の理由がモデルに返っている
    assert cases[0]["tool_calls"] == [{"tool": "save_learning_log", "args": {"title": "t", "content": "c"}}]
    assert cases[0]["requests"] == 2
    assert not isolated_learning_log.exists()  # 評価セットの生成ではファイルを作らない


def test_main_runs_all_conditions_with_fake_model_and_resumes(tmp_path, monkeypatch):
    """ラベルを講師のもので代用し、偽モデルで全条件を流す。もう一度実行したら採点し直さない。"""
    labels = tmp_path / "labels.jsonl"
    shutil.copy(d4.INSTRUCTOR_LABELS, labels)
    my_cases, my_labels = tmp_path / "my_cases.jsonl", tmp_path / "my_labels.jsonl"
    cases = judge.read_jsonl(d4.MY_CASES)
    for c in cases:
        c["answer"] = "用語集にはありません。\n\n関係する回：第4回"
        c["tool_calls"] = [{"tool": "search_glossary", "args": {"query": "x"}}]
    judge.write_jsonl(my_cases, cases)
    judge.write_jsonl(my_labels, [{"id": c["id"], **{k: "pass" for k, _ in judge.ALL_CRITERIA}} for c in cases])

    swap = {judge.DEFAULT_LABELS: labels, d4.MY_CASES: my_cases, d4.MY_LABELS: my_labels}
    monkeypatch.setattr(d4, "CONDITIONS", [tuple(swap.get(x, x) for x in cond) for cond in d4.CONDITIONS])
    monkeypatch.setattr(d4, "MY_CASES", my_cases)
    monkeypatch.setattr(d4, "MY_LABELS", my_labels)
    monkeypatch.setattr(d4, "L4", tmp_path)
    monkeypatch.setattr(judge, "DEFAULT_LABELS", labels)

    d4.main(["--model", "test"])
    out = tmp_path / "results_test"
    names = [c[0] for c in d4.CONDITIONS]
    assert all((out / f"{n}.json").exists() for n in names)
    before, base = (json.loads((out / f"{n}.json").read_text(encoding="utf-8")) for n in ("ex_before", "baseline"))
    assert len(before["summary"]["review"]) == 1 and len(base["summary"]["review"]) == 0  # 方針を書き足すと要確認が消える
    assert d4.flips(base, before) and not d4.flips(base, json.loads((out / "baseline_2.json").read_text(encoding="utf-8")))

    stamp = (out / "baseline.json").stat().st_mtime_ns
    d4.main(["--model", "test"])
    assert (out / "baseline.json").stat().st_mtime_ns == stamp
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "| my_cases" in summary and "自分の評価セット：コードで決まる確認" in summary and "講師のラベル" in summary


def test_lecture_mark_v2_checks_whether_the_shown_lecture_is_appropriate():
    case = lambda q, a, refs=(): {"question": q, "answer": a, "reference": {"glossary": list(refs)}}
    assert d4.check_lecture_mark_v2(case("LoRAとは？", "説明\n\n関係する回：第2回", ["lora"])) == "pass"
    assert d4.check_lecture_mark_v2(case("LoRAとは？", "説明\n\n関係する回：第3回", ["lora"])) == "fail"  # 参照の回と違う
    assert d4.check_lecture_mark_v2(case("LoRAとは？", "説明だけ", ["lora"])) == "fail"  # 示していない
    assert d4.check_lecture_mark_v2(case("天気は？", "範囲外です。\n\n関係する回：なし")) == "pass"  # 関係する回が無い
    assert d4.check_lecture_mark_v2(case("天気は？", "範囲外です。\n\n関係する回：第1回")) == "fail"  # 根拠のない回
    assert d4.check_lecture_mark_v2(case("第4回の宿題は？", "ヒント\n\n第4回")) == "pass"  # 質問で名指しされた回
    assert d4.check_lecture_mark_v2(case("第14回の要点は？", "ありません\n\n関係する回：第14回")) == "fail"  # 存在しない回
    assert d4.check_lecture_mark_v2(case("第14回の要点は？", "ありません\n\n（関連する回：該当なし）")) == "pass"
