"""第3回 宿題（実装）: save_learning_log と、保存前の承認（Human-in-the-loop）のテスト。

LLM も API キーも使わない。TestModel に save_learning_log だけを呼ばせ、
「承認待ちで止まる → 承認なら保存・拒否なら保存しない」を確かめる。
学習ログの保存先は conftest.py で一時フォルダに差し替えている。
"""

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app import tools
from app.agent import DENIED_MESSAGE, agent, run_with_approval


def _parts(result, kind):
    return [p for m in result.all_messages() for p in m.parts if isinstance(p, kind)]


def _save_only_model() -> TestModel:
    return TestModel(call_tools=["save_learning_log"])


# --- ツール単体 ---------------------------------------------------------------


def test_save_writes_markdown(isolated_learning_log):
    message = tools.save_learning_log("LoRAとQLoRAの違い", "QLoRAは量子化した基盤モデルにLoRAを使う。", 2)
    files = list(isolated_learning_log.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("# LoRAとQLoRAの違い\n")
    assert "- 関係する回: 第2回" in text
    assert "QLoRAは量子化した基盤モデルにLoRAを使う。" in text
    assert files[0].name in message and "保存しました" in message


def test_save_never_overwrites(isolated_learning_log):
    tools.save_learning_log("同じタイトル", "1回目")
    tools.save_learning_log("同じタイトル", "2回目")
    texts = sorted(p.read_text(encoding="utf-8") for p in isolated_learning_log.glob("*.md"))
    assert len(texts) == 2
    assert any("1回目" in t for t in texts) and any("2回目" in t for t in texts)


def test_save_keeps_files_inside_log_dir(isolated_learning_log):
    """モデルが作ったタイトルに / や .. が入っても、learning_log/ の外には書かない。"""
    tools.save_learning_log("../../etc/passwd", "外に出ないこと")
    files = list(isolated_learning_log.glob("*.md"))
    assert len(files) == 1
    assert files[0].resolve().parent == isolated_learning_log.resolve()


def test_save_rejects_empty_or_too_long(isolated_learning_log):
    assert "保存していません" in tools.save_learning_log("  ", "本文")
    assert "保存していません" in tools.save_learning_log("見出し", "")
    too_long = "あ" * (tools.MAX_LOG_CONTENT_CHARS + 1)
    assert "保存していません" in tools.save_learning_log("見出し", too_long)
    assert not isolated_learning_log.exists() or not list(isolated_learning_log.iterdir())


# --- エージェント経由（承認の流れ） --------------------------------------------


def test_save_is_registered_as_requiring_approval():
    model = TestModel(call_tools=[])
    agent.run_sync("ツール一覧", model=model)
    kinds = {t.name: t.kind for t in model.last_model_request_parameters.function_tools}
    assert kinds["save_learning_log"] == "unapproved"
    assert kinds["search_glossary"] == "function"  # 読むだけのツールには承認を求めない


def test_run_stops_before_saving(isolated_learning_log):
    """1回目の実行は、保存する前に承認待ちで止まり DeferredToolRequests を返す。"""
    result = agent.run_sync("今日の学びを記録して", model=_save_only_model())
    assert isinstance(result.output, DeferredToolRequests)
    assert [c.tool_name for c in result.output.approvals] == ["save_learning_log"]
    assert not _parts(result, ToolReturnPart)  # まだ実行されていない
    assert not isolated_learning_log.exists()


def test_approved_call_saves_and_continues(isolated_learning_log):
    seen = []

    def approve(call: ToolCallPart) -> bool:
        seen.append(call.tool_name)
        return True

    result = run_with_approval(agent, "今日の学びを記録して", _save_only_model(), approve=approve)

    assert seen == ["save_learning_log"]  # 利用者に1回だけ聞いた
    assert isinstance(result.output, str)  # 承認後は最後まで進み、文章の回答になる
    assert len(list(isolated_learning_log.glob("*.md"))) == 1
    returns = _parts(result, ToolReturnPart)
    assert returns[-1].tool_name == "save_learning_log"
    assert "保存しました" in str(returns[-1].content)
    assert result.usage.requests == 2  # 止まる前の1回 + 続きの1回（usage を引き継いで合計）


def test_denied_call_does_not_save(isolated_learning_log):
    result = run_with_approval(agent, "今日の学びを記録して", _save_only_model(), approve=lambda call: False)

    assert isinstance(result.output, str)
    assert not isolated_learning_log.exists() or not list(isolated_learning_log.glob("*.md"))
    returns = _parts(result, ToolReturnPart)
    assert returns[-1].tool_name == "save_learning_log"
    assert returns[-1].content == DENIED_MESSAGE  # 拒否した理由がモデルに返る


def test_cli_prompt_denies_when_input_is_not_y(monkeypatch, isolated_learning_log, capsys):
    """CLI の確認（ask_approval）は y / yes 以外なら拒否する。Enter だけでも保存しない。"""
    from app.agent import ask_approval

    call = ToolCallPart("save_learning_log", {"title": "見出し", "content": "本文", "lecture": 3})
    for answer, expected in [("y", True), ("YES", True), ("", False), ("n", False), ("はい", False)]:
        monkeypatch.setattr("builtins.input", lambda prompt, a=answer: a)
        assert ask_approval(call) is expected, answer
    shown = capsys.readouterr().out
    assert "[承認待ち]" in shown and "title: 見出し" in shown and "lecture: 3" in shown
