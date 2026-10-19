"""比較記録の欠落や上書きを防ぐ。回答の品質や速度を検証するテストではない。"""

import json

import pytest
from google import genai
from google.genai import errors, types

from scripts import day1_compare


def test_three_repeats_per_question_and_failures_remain(tmp_path, monkeypatch):
    client = genai.Client(api_key="offline-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-key")
    monkeypatch.setattr(day1_compare.genai, "Client", lambda **kwargs: client)
    monkeypatch.setattr(day1_compare, "QUESTIONS", ["一般的な質問", "講座固有の質問"])
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise errors.ClientError(429, {"message": "do-not-write-secret"})
        return types.GenerateContentResponse(
            candidates=[types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text="テスト用の返答")]),
            )],
            model_version="returned-model",
        )

    monkeypatch.setattr(client.models, "generate_content", generate)
    path = tmp_path / "results.jsonl"
    failures = day1_compare.run(["model-a", "model-b"], path, interval=0)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 12
    assert failures == 1
    assert rows[1]["status"] == "api_error" and rows[1]["http_status"] == 429
    assert rows[0]["tokens"]["prompt_token_count"] is None
    assert rows[0]["model_returned"] == "returned-model"
    assert "do-not-write-secret" not in path.read_text(encoding="utf-8")
    for model in ["model-a", "model-b"]:
        for question in day1_compare.QUESTIONS:
            assert [r["repeat"] for r in rows if r["model_requested"] == model
                    and r["question"] == question] == [1, 2, 3]
    with pytest.raises(FileExistsError):
        day1_compare.run(["model-a"], path, interval=0)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 12
