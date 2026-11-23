# 第6回 実行記録

## 実行環境

- 実行日：2026年11月24日
- 実測環境：GitHub Codespaces、Python 3.12、教材の依存関係を `uv sync --frozen` で導入
- モデル：`gemini-3.6-flash`（教材の既定モデルと代替モデルで503が発生したため変更）
- 以下のツール戻り値は、教材の `--trace` が先頭120文字まで表示した内容の抜粋。

## 演習

STEP 1 の一覧では、従来のエージェントに `search_materials`、MCP エージェントに `glossary_search_glossary` が表示された。fetch と AWS を設定すると、それぞれのサーバーに接続し、ツール一覧を取得できた。

### STEP 2：用語集

質問：AIE2026の講座の宿題にある「3レベル」とは何ですか？

```text
[tool call]   glossary_search_glossary({'query': '3レベル'})
[tool return] glossary_search_glossary -> [{"term": "宿題の3レベル", "lecture": 1, "definition": "AIE2026の宿題の構成。「基礎（講義内容の確認）」「実装（自分でコードを書く）」「発展（調査や試行）」の3段階があり、どれか1つに取り組…
[usage] 入力 5,715 tokens / 出力 687 tokens / モデル応答 2 回
```

### STEP 3：fetch

質問：https://modelcontextprotocol.io/ の冒頭を日本語で3行に要約して

```text
[tool call]   glossary_search_glossary({'query': 'Model Context Protocol'})
[tool call]   fetch_fetch({'url': 'https://modelcontextprotocol.io/'})
[tool return] glossary_search_glossary -> [{"term": "MCP（Model Context Protocol）", "lecture": 3, "definition": "AIアプリと外部のツールやデータソースをつなぐためのオープンな標準プロトコル。MCPサーバーとして公…
[tool return] fetch_fetch -> Contents of https://modelcontextprotocol.io/:
> ## Documentation Index
> Fetch the complete documentation index at: http…
[usage] 入力 6,814 tokens / 出力 1,165 tokens / モデル応答 2 回
```

### STEP 4：AWS Knowledge

AWSサーバーの接続とツール一覧の取得を確認した。S3のバージョニングについて検索する質問は `gemini-3.6-flash` と `gemini-3.7-flash` で再試行したが、モデル側で503が発生し、ツール呼び出しの trace は得られなかった。

## 宿題：基礎

演習の設定変更を区切った後、サーバー側の `app/mcp_server.py` のみを変更した。ツール一覧に `glossary_get_lecture_summary` が増えた。教材のテストは `21 passed in 4.22s`。

質問：第2回では何を学びますか？

```text
[tool call]   glossary_get_lecture_summary({'lecture': 2})
[tool return] glossary_get_lecture_summary -> # 第2回 ファインチューニングとLoRA

## この回のねらい

- 事前学習とファインチューニングの違い、ファインチューニングが向く場面と向かない場面を理解する
- LoRAの考え方を理解し、Google Colab上で小さなモデルを…
[usage] 入力 6,016 tokens / 出力 531 tokens / モデル応答 2 回
```

## 宿題：実装

質問：第2回の復習クイズを作って

```text
[tool call]   glossary_make_quiz({'lecture': 2})
[tool return] glossary_make_quiz -> 第2回の復習クイズ
1. 「事前学習」とは何か、説明してください。
2. 「ファインチューニング」とは何か、説明してください。
3. 「教師ありファインチューニング（SFT）」とは何か、説明してください。…
[usage] 入力 5,900 tokens / 出力 414 tokens / モデル応答 2 回
```

質問：第99回のクイズを作って

```text
[tool call]   glossary_make_quiz({'lecture': 99})
[tool return] glossary_make_quiz -> 第99回は範囲外です。クイズを作れる回：第1回、第2回、第3回、第4回、第6回。…
[usage] 入力 5,823 tokens / 出力 463 tokens / モデル応答 2 回
```

モデルの最終回答：

> 申し訳ありませんが、第99回は本講座の範囲外のため、クイズを作成することができません。
>
> 現在クイズを作成できる回は以下の通りです。
> * 第1回
> * 第2回
> * 第3回
> * 第4回
> * 第6回
>
> クイズを作成したい回がございましたら、上記の回を指定してお知らせください。
>
> （関係する回：第1回、第2回、第3回、第4回、第6回）

用語集にデータがない第5回と範囲外の回を区別するケースを含め、実際のMCP通信を使うテストを追加し、Windows環境で全22件が成功した。
