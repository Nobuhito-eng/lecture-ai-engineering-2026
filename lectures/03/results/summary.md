# 第3回 基礎：INSTRUCTIONS / docstring の比較（自動集計）

- 集計日時: 2026-11-04T03:02:35+09:00
- 成功した実行: 27 件、失敗: 0 件
- モデル: gemini-3.5-flash-lite
- 数値は成功した実行の平均。自動チェックは目安で、最終判断は day3_runs.jsonl の回答本文で行う
- 混雑（503）・レート制限（429）で再実行した回数: 4
- 「最終行が第N回」は、最後の行が「（第2回）」「関係する回：第2回」のように回だけを示す行かどうか

| 変種 | 質問 | 成功/試行 | search回数 | requests | 入力tok | 出力tok | 最終行が第N回 | 本文に第N回 | その他 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | levels | 3/3 | 1.00 | 2.00 | 1429.00 | 160.67 | 3/3 | 3/3 | 3レベル 3/3; どれか1つ 3/3 |
| baseline | lora | 3/3 | 2.00 | 2.00 | 1842.00 | 215.67 | 3/3 | 3/3 | 量子化 3/3; query ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] |
| baseline | quiz | 3/3 | 0.00 | 2.00 | 1381.67 | 54.33 | 3/3 | 3/3 | make_quiz呼出 3/3; summary呼出 0/3; 答えまで表示 0/3 |
| no_must_search | levels | 3/3 | 1.00 | 2.00 | 1381.00 | 153.67 | 3/3 | 3/3 | 3レベル 3/3; どれか1つ 3/3 |
| no_must_search | lora | 3/3 | 2.00 | 2.00 | 1794.00 | 171.67 | 3/3 | 3/3 | 量子化 3/3; query ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] |
| search_bulk | lora | 3/3 | 1.00 | 2.00 | 1537.00 | 240.00 | 3/3 | 3/3 | 量子化 3/3; query ["LoRA QLoRA"] / ["LoRA QLoRA"] / ["LoRA QLoRA"] |
| no_lecture_ref | levels | 3/3 | 1.00 | 2.00 | 1395.00 | 146.33 | 0/3 | 2/3 | 3レベル 3/3; どれか1つ 3/3 |
| no_lecture_ref | lora | 3/3 | 2.00 | 2.00 | 1808.00 | 225.00 | 0/3 | 3/3 | 量子化 3/3; query ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] / ["LoRA", "QLoRA"] |
| no_quiz_line | quiz | 3/3 | 0.00 | 2.00 | 1348.00 | 68.33 | 2/3 | 3/3 | make_quiz呼出 3/3; summary呼出 0/3; 答えまで表示 0/3 |

## 変種の説明

- `baseline`（-）: 変更なし（演習・実装を終えた状態）
- `no_must_search`（INSTRUCTIONS）: INSTRUCTIONS から「必ず search_glossary で用語集を確認する」の行を消す
- `search_bulk`（docstring:search_glossary）: search_glossary の docstring の「1つだけ」を「まとめて」に変える
- `no_lecture_ref`（INSTRUCTIONS）: INSTRUCTIONS から「回答の最後に、関係する回（第N回）を示す」の行を消す
- `no_quiz_line`（INSTRUCTIONS）: INSTRUCTIONS から「確認問題を求められたら make_quiz を使う」の行を消す（docstring だけで呼ばれるか）
