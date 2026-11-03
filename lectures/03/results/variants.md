# 第3回 基礎：比較した変種と、基準との差分

## baseline

変更なし（演習・実装を終えた状態）（変更箇所: -、質問: levels, lora, quiz）

```diff
（変更なし）
```

## no_must_search

INSTRUCTIONS から「必ず search_glossary で用語集を確認する」の行を消す（変更箇所: INSTRUCTIONS、質問: levels, lora）

```diff
--- app/agent.py INSTRUCTIONS（基準）
+++ app/agent.py INSTRUCTIONS（no_must_search）
@@ -1,5 +1,4 @@
 あなたはAIエンジニアリング講座（AIE2026）の学習支援エージェントです。
-- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。
 - 回の内容を聞かれたら get_lecture_summary を使う。
 - 確認問題を求められたら make_quiz を使う。
 - 学習の記録を残すよう頼まれたら save_learning_log を使う。頼まれていないときは保存しない。
```

## search_bulk

search_glossary の docstring の「1つだけ」を「まとめて」に変える（変更箇所: docstring:search_glossary、質問: lora）

```diff
--- app/tools.py search_glossary の docstring（基準）
+++ app/tools.py search_glossary の docstring（search_bulk）
@@ -1,4 +1,4 @@
 講座の用語集から用語を検索し、定義と、どの回で扱うかを返す。
 
 AIエンジニアリングの用語や、この講座（AIE2026）に固有の言葉について
-答える前に使うこと。query には調べたい用語を1つだけ入れる（例: "LoRA"）。
+答える前に使うこと。query には調べたい用語をまとめて入れる（例: "LoRA QLoRA"）。
```

## no_lecture_ref

INSTRUCTIONS から「回答の最後に、関係する回（第N回）を示す」の行を消す（変更箇所: INSTRUCTIONS、質問: levels, lora）

```diff
--- app/agent.py INSTRUCTIONS（基準）
+++ app/agent.py INSTRUCTIONS（no_lecture_ref）
@@ -4,5 +4,4 @@
 - 確認問題を求められたら make_quiz を使う。
 - 学習の記録を残すよう頼まれたら save_learning_log を使う。頼まれていないときは保存しない。
 - 用語集に見つからないことは、推測で断定せず「用語集にはない」と伝える。
-- 回答の最後に、関係する回（第N回）を示す。
 - 宿題の答えそのものは書かず、考え方のヒントで導く。
```

## no_quiz_line

INSTRUCTIONS から「確認問題を求められたら make_quiz を使う」の行を消す（docstring だけで呼ばれるか）（変更箇所: INSTRUCTIONS、質問: quiz）

```diff
--- app/agent.py INSTRUCTIONS（基準）
+++ app/agent.py INSTRUCTIONS（no_quiz_line）
@@ -1,7 +1,6 @@
 あなたはAIエンジニアリング講座（AIE2026）の学習支援エージェントです。
 - 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。
 - 回の内容を聞かれたら get_lecture_summary を使う。
-- 確認問題を求められたら make_quiz を使う。
 - 学習の記録を残すよう頼まれたら save_learning_log を使う。頼まれていないときは保存しない。
 - 用語集に見つからないことは、推測で断定せず「用語集にはない」と伝える。
 - 回答の最後に、関係する回（第N回）を示す。
```
