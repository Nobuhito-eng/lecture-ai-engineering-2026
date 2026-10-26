"""保存した出力原文から採点と比較条件を再確認する（追加ライブラリ不要）。"""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "results"
RUNS = ["baseline", "basic_epochs10", "implementation"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def score(raw, gold):
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        obj = None
    fmt = (
        isinstance(obj, dict)
        and set(obj) == {"answer", "needs_review"}
        and isinstance(obj["answer"], str)
        and type(obj["needs_review"]) is bool
    )
    if not fmt:
        match = re.search(r"\{.*\}", raw, re.S)
        try:
            obj = json.loads(match.group()) if match else None
        except json.JSONDecodeError:
            obj = None
    content = (
        isinstance(obj, dict)
        and obj.get("needs_review") == gold["needs_review"]
        and all(word in obj.get("answer", "") for word in gold["must_include"])
    )
    return fmt, content


def verify():
    results = {}
    for run in RUNS:
        folder = ROOT / run
        result = read_json(folder / "result.json")
        results[run] = result
        assert result["run"] == run
        assert result["executed_training_myself"] is True
        data = {split: read_jsonl(folder / f"{split}.jsonl") for split in ("train", "valid", "test")}
        assert {key: len(value) for key, value in data.items()} == {"train": 14, "valid": 7, "test": 21}
        questions = [row["question"] for values in data.values() for row in values]
        assert len(questions) == len(set(questions)), f"{run}: split間の質問重複"
        gold = read_json(folder / "gold.json")
        assert set(gold) == {row["question"] for row in data["test"]}
        assert sum(row["needs_review"] for row in data["test"]) == 6
        evaluated = {}
        for label in ("before", "after"):
            evaluation = read_json(folder / f"eval_{label}.json")
            rows = evaluation["rows"]
            assert [r["question"] for r in rows] == [r["question"] for r in data["test"]]
            counts = {"format": 0, "content": 0, "both": 0}
            for row in rows:
                fmt, content = score(row["raw"], gold[row["question"]])
                assert (fmt, content, fmt and content) == (row["format_ok"], row["content_ok"], row["both_ok"])
                assert row["gold_needs_review"] == gold[row["question"]]["needs_review"]
                counts["format"] += fmt
                counts["content"] += content
                counts["both"] += fmt and content
            for key, count in counts.items():
                rate = count / len(rows)
                assert math.isclose(rate, evaluation["summary"][f"{key}_rate"])
                assert math.isclose(rate, result[label][f"{key}_rate"])
            assert result[label] == evaluation["summary"]
            evaluated[label] = rows
            print(f"{run:16} {label:6} format={counts['format']}/21 content={counts['content']}/21")
        regressed = [b["question"] for b, a in zip(evaluated["before"], evaluated["after"]) if b["both_ok"] and not a["both_ok"]]
        assert regressed == result["regressed"]
        training = read_json(folder / "training.json")
        assert training == result["training"]
        assert training["seconds"] > 0 and math.isfinite(training["final_logged_loss"])
        assert training["global_step"] == result["config"]["num_train_epochs"] * 2
        assert training["fp16"] is False and training["bf16"] is False
        assert training["final_loss_step"] == training["global_step"]
        assert training["final_logged_loss"] == [r for r in training["logs"] if "loss" in r][-1]["loss"]
        assert len(result["knowledge"]) == 4
        assert [r["FAQ にある"] for r in result["knowledge"]] == [False, False, False, True]

    base, basic = results["baseline"], results["basic_epochs10"]
    changed = {k for k in base["config"] if base["config"][k] != basic["config"][k]}
    assert changed == {"num_train_epochs"}, changed
    for name in ("train.jsonl", "valid.jsonl", "test.jsonl", "gold.json"):
        assert (ROOT / "baseline" / name).read_bytes() == (ROOT / "basic_epochs10" / name).read_bytes()
    assert base["config"] == results["implementation"]["config"]
    assert len({r["gpu"] for r in results.values()}) == 1
    assert all(r["versions"] == base["versions"] for r in results.values())
    print("OK: 全126回答の再採点、データ分割、設定差分、損失・時間・退行を検証しました。")


if __name__ == "__main__":
    verify()
