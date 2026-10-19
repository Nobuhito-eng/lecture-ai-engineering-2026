"""実際の SDK の履歴処理を使う。API 呼び出しだけ差し替える（実測ではない）。"""

from copy import deepcopy

import pytest
from google import genai
from google.genai import errors, types

from app import ask


def response(text="最初の説明", usage=True):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            finish_reason="STOP",
        )],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=12, candidates_token_count=7,
        ) if usage else None,
    )


@pytest.fixture
def sdk(monkeypatch):
    client = genai.Client(api_key="offline-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-key")
    monkeypatch.setattr(ask.genai, "Client", lambda **kwargs: client)
    return client


def feed(monkeypatch, inputs):
    items = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt: next(items))


def test_chat_sends_both_roles_from_previous_turn(sdk, monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(deepcopy(kwargs["contents"]))
        return response()

    monkeypatch.setattr(sdk.models, "generate_content", generate)
    feed(monkeypatch, ["LoRAとは？", "それを一文で", "/exit"])
    ask.chat()
    assert [part.role for part in calls[1]] == ["user", "model", "user"]
    assert [part.parts[0].text for part in calls[1]] == [
        "LoRAとは？", "最初の説明", "それを一文で",
    ]


def test_failed_turn_is_not_added_to_history(sdk, monkeypatch, capsys):
    calls = []

    def generate(**kwargs):
        calls.append(deepcopy(kwargs["contents"]))
        if len(calls) == 2:
            raise errors.ClientError(429, {"message": "do-not-display-secret"})
        return response()

    monkeypatch.setattr(sdk.models, "generate_content", generate)
    feed(monkeypatch, ["最初の質問", "失敗する質問", "もう一度質問", "/exit"])
    ask.chat()
    assert [part.parts[0].text for part in calls[2]] == [
        "最初の質問", "最初の説明", "もう一度質問",
    ]
    output = capsys.readouterr().out
    assert "レート制限" in output
    assert "do-not-display-secret" not in output


def test_empty_input_and_exit_do_not_call_api(sdk, monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("空入力や終了入力で API を呼んだ")

    monkeypatch.setattr(sdk.models, "generate_content", forbidden)
    feed(monkeypatch, ["   ", "/exit"])
    ask.chat()


@pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
def test_chat_accepts_terminal_end(sdk, monkeypatch, interrupt):
    def end(prompt):
        raise interrupt

    monkeypatch.setattr("builtins.input", end)
    ask.chat()


def test_chat_accepts_first_question(sdk, monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(deepcopy(kwargs["contents"]))
        return response()

    monkeypatch.setattr(sdk.models, "generate_content", generate)
    feed(monkeypatch, ["/exit"])
    ask.chat("最初の質問")
    assert calls[0][0].parts[0].text == "最初の質問"


def test_single_question_remains_stateless(sdk, monkeypatch, capsys):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs["contents"])
        return response("単発の回答")

    monkeypatch.setattr(sdk.models, "generate_content", generate)
    assert ask.ask("質問") == "単発の回答"
    assert calls == ["質問"]
    assert "input=12 output=7" in capsys.readouterr().out


def test_unavailable_usage_is_not_reported_as_zero(capsys):
    ask.print_usage(response(usage=False))
    assert "input=不明 output=不明" in capsys.readouterr().out


def test_missing_key_stops_before_api(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        ask.ask("質問")
