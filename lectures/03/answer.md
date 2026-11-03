# 第3回 解答

## 取り組んだレベルと実行環境

- 提出フォームの選択：**実装**。基礎と実装の両方に取り組んだ（発展は対象外）。宿題の前提として、演習の手順4（`make_quiz`）も行った。
- 実行日：2026年11月4日（日本時間）。
- 実APIの実行環境：自分の fork の GitHub Codespaces / Linux / Python 3.12.16（`lectures/03/results/environment.json`）。
- 依存関係：講座の `uv.lock` を変更せず使用。pydantic-ai-slim 2.57.0、google-genai 2.31.0。
- モデル：`gemini-3.5-flash-lite`（既定）。temperature などの生成設定は指定せず、既定値のまま。
- APIキーは Codespaces secret から読み込み、コード・回答・記録には保存していない。
- 実行は `uv run --frozen python -m scripts.day3_compare` で行い、記録はすべて `lectures/03/results/` に置いた。AI ツール（Claude）でコードを書き、実行と結果の確認は自分の Codespaces で行った。

## 演習

同じ質問を基準のエージェントで各3回実行した（下の「基礎」の `baseline` と同じ記録）。

- **第1回（素のLLM）とエージェントの回答の違い**：「AIE2026の講座の宿題にある「3レベル」とは何ですか？」に対して、第1回の `app.ask` は3回とも講座を特定できず、2回は一般的な「基礎・応用・発展」の説明、1回は「講座の詳細は知らない」と明示した一般論だった（第1回の記録：`lec01` ブランチの `lectures/01/results/comparison_20261020_codespaces.jsonl`）。エージェントは3回とも先に `search_glossary` で用語集を引き、「基礎・実装・発展」「どれか1つに取り組めば完了」「原則として採点しない」という `homework-levels` の定義どおりに答え、最後に第1回を示した。ただし括弧内の補足（例：「知識の定着を目的とした問題など」）は用語集にない言い換えで、モデルが付け足したものだった。
- **`--trace` で見えたツール呼び出し（ツール名と引数）**：

  | 質問 | ツール呼び出し（3回とも同じ） |
  |---|---|
  | 「3レベル」とは | `search_glossary({'query': '3レベル'})` |
  | LoRAとQLoRAの違いは？ | `search_glossary({'query': 'LoRA'})`、`search_glossary({'query': 'QLoRA'})` |
  | 第2回の内容から確認問題を1問出して | `make_quiz({'lecture': 2})`（`get_lecture_summary` は呼ばれない） |

  ```text
  --- trace ---
  [tool call]   search_glossary({'query': 'LoRA'})
  [tool call]   search_glossary({'query': 'QLoRA'})
  [tool return] search_glossary -> [{"term": "LoRA", "lecture": 2, "definition": "事前学習済みの重みは固定したまま、…
  [tool return] search_glossary -> [{"term": "QLoRA", "lecture": 2, "definition": "ベースモデルの重みを4ビットなどに…
  [usage] RunUsage(… input_tokens=1842, output_tokens=212, requests=2, tool_calls=2)
  ```

- **1つの質問での LLM 呼び出し回数（`requests`）**：基礎の27回すべてで `requests=2`。LoRA と QLoRA の2回の検索も、1回目の応答で同時に（並列に）依頼されていたため、`tool_calls=2` でも `requests=2` だった。保存まで行った実装の実行では、承認の前後で `requests=3` になった（後述）。
- **追加したツールと、docstring に書いた説明**：`make_quiz(lecture: int)`。指定した回の用語集から用語を1つ選び、`{"question": "「○○」の意味は？", "answer": <用語集の定義>}` を返す。存在しない回（0 や 4 など）では、問題を作れる回の一覧を返して落ちない。docstring は次のとおり。INSTRUCTIONS にも「確認問題を求められたら make_quiz を使う。」を1行足した。

  ```text
  指定した回の用語集から用語を1つ選び、確認問題と答えを返す。
  「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う。
  lecture には回の番号（1始まりの整数）を入れる。
  ```

## 宿題

- **取り組んだレベル**：基礎・実装（最高レベル：**実装**）

### 実装：保存の前に利用者の確認を挟む

**やったこと**

- `app/tools.py` に `save_learning_log(title, content, lecture=0)` を追加した。`learning_log/`（`.gitignore` 済み）に「日時_タイトル.md」を作り、見出し・日時・関係する回・本文を書く。
- 保存は取り消しにくい操作なので、ツールの中でも次の安全策を入れた。
  - 既存のファイルは上書きしない（`open(..., "x")`。同名なら連番を付ける）
  - タイトルに `/` や `..` が入っても `learning_log/` の外に書かない（文字・数字・ハイフン以外は `-` に置き換える）
  - 空のタイトルや本文、長すぎる入力は保存せず、理由を返す
- docstring には「記録や保存をはっきり頼んだときだけ使う。質問に答えるだけのときは使わない。実行の前に利用者の承認が必要」と書き、INSTRUCTIONS にも「学習の記録を残すよう頼まれたら save_learning_log を使う。頼まれていないときは保存しない。」を足した。
- `app/agent.py` で `requires_approval=True` を付けて登録し、`output_type=[str, DeferredToolRequests]` にした。
- CLI の流れ（`run_with_approval`）は次のとおり。
  1. 実行が `DeferredToolRequests` で止まったら、モデルが渡そうとしている引数（title・content・lecture）を全部表示し、`保存してよいですか？ [y/N]` と聞く。
  2. `y` / `yes` なら承認（`True`）、それ以外なら拒否（`ToolDenied("利用者が承認しなかったため、保存していません。…")`）にする。Enter だけや、入力できない環境（EOF）でも拒否にして、安全側に倒した。
  3. `message_history=result.all_messages()` と `deferred_tool_results` を渡して、止まったところから続きを実行する。`usage=result.usage` も渡し、承認の前後の LLM 呼び出しを合計して表示する。
  4. 承認待ちが続く場合に備え、5回で打ち切る。
- テスト（TestModel、APIキー不要）を `tests/test_learning_log.py` に9件書いた。確かめたのは、ツール単体の保存・上書きしないこと・保存先の外に出ないこと・空や長すぎる入力の拒否と、エージェント経由の「保存前に止まり、まだファイルがない」「承認なら保存して最後まで進む（`requests=2`）」「拒否なら保存せず、拒否の理由がモデルに返る」「ツール定義の種類が `unapproved` になる」「CLI は y / yes 以外を拒否する」。学習ログは `tests/conftest.py` で一時フォルダに書かせ、本物の `learning_log/` は汚さない。
- 既存の `test_base_tools_are_registered_and_called` は最小限だけ変えた。TestModel は登録された全ツールを呼ぶが、承認待ちの `save_learning_log` にはその時点で戻り値がないため、「呼び出し数＝戻り値数」が成り立たなくなる。承認待ちを拒否で解決してから数えるようにした。

**結果**

- `uv run pytest -q`：Codespaces で **28 passed**（`lectures/03/results/pytest.txt`）。その後、自動チェックのテストを1件足して29件になった。
- 実モデルでの承認（y）：`uv run python -m app.agent --trace "LoRAとQLoRAの違いを用語集で調べて、学習ログに保存して"` に `y` を入力した（`lectures/03/results/cli_save_approve.txt`）。

  ```text
  [承認待ち] モデルが save_learning_log の実行を求めています（learning_log/ にファイルを保存します）
    content: ### LoRA と QLoRA の違い …（モデルがまとめた本文）
    lecture: 2
    title: LoRAとQLoRAの違い
  保存してよいですか？ [y/N]: [approval]    save_learning_log -> 承認
  …（回答本文）…
  --- trace ---
  [tool call]   search_glossary({'query': 'LoRA'})
  [tool call]   search_glossary({'query': 'QLoRA'})
  [tool call]   save_learning_log({'content': '### LoRA と QLoRA の違い …', 'lecture': 2, 'title': 'LoRAとQLoRAの違い'})
  [tool return] save_learning_log -> 学習ログを保存しました: learning_log/20261103-173336_LoRAとQLoRAの違い.md…
  [usage] RunUsage(… input_tokens=3282, output_tokens=356, requests=3, tool_calls=3)
  ```

  検索2回（1回目の応答）→ 保存の依頼（2回目の応答）で止まり、承認後に続き（3回目の応答）を実行して回答した。`learning_log/` にファイルが1つ増え、承認画面に表示された本文と同じ内容が保存されていた。
- 実モデルでの拒否（n）：1回目の実行はモデルの混雑（HTTP 503）で失敗し、モデルまで届かなかった（`lectures/03/results/cli_save_deny.txt`）。拒否したときに保存されず、拒否の理由がモデルに返ることは、TestModel のテストで確認している。
- 保存を頼んでいない基礎の27回では、`save_learning_log` は一度も呼ばれなかった。

**気づき・疑問**

- 承認画面で本文を全部見せたのは意味があった。保存されたのは用語集の定義そのものではなく、モデルが言い換えた文（「（Quantization）」の付記など）だったからだ。何を残すかを人が確認できるのが、Human-in-the-loop の役割だと分かった。
- 承認の前後で `run_sync` が2回に分かれる。`usage` を引き継がないと、`requests` が実際より少なく見える。
- 疑問：拒否されたモデルが、同じ保存をもう一度依頼してきたらどうするか。今回はプログラム側で上限を5回にしたが、「拒否されたら同じ会話では再依頼しない」を INSTRUCTIONS に書くべきか、プログラム側で止めるべきか。

### 基礎：INSTRUCTIONS / docstring を1か所ずつ変えて比べる

**やったこと**

- 演習・実装を終えた状態を基準（`baseline`）にして、1か所だけ変えた4つの変種を作った。差分は `lectures/03/results/variants.md` に置いた。

  | 変種 | 変えた場所 | 変更内容 | 質問 |
  |---|---|---|---|
  | `no_must_search` | INSTRUCTIONS | 「用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。」の行を消す | 3レベル、LoRA |
  | `search_bulk` | `search_glossary` の docstring | 「query には調べたい用語を1つだけ入れる（例: "LoRA"）」を「まとめて入れる（例: "LoRA QLoRA"）」に変える | LoRA |
  | `no_lecture_ref` | INSTRUCTIONS | 「回答の最後に、関係する回（第N回）を示す。」の行を消す | 3レベル、LoRA |
  | `no_quiz_line` | INSTRUCTIONS | 「確認問題を求められたら make_quiz を使う。」の行を消す | 確認問題 |

- `app/` のファイルを手で書き換えて戻す代わりに、スクリプトの中で変種のエージェントを組み立てた。「基準が講座のエージェントとまったく同じ指示・ツール定義になること」「変種は1か所だけ違うこと」は `tests/test_day3_compare.py` で確かめてある。
- 各条件・各質問を3回ずつ、合計27回実行した。実行の間には10秒待った。混雑（HTTP 503）が4回起き、30秒待った再実行ですべて成功した。応答時間は20〜94秒（中央値35秒）とばらつきが大きく、混雑の影響と区別できないので、比較には使わない。

**結果**（3回の平均。詳細は `summary.md` と `day3_runs.jsonl`。自動チェックの値は回答本文を読んで確かめた）

| 変種 | 質問 | search 回数 | 検索語（3回） | requests | 入力tok | 出力tok | 最終行が「第N回」 |
|---|---|---:|---|---:|---:|---:|---:|
| baseline | 3レベル | 1 | `3レベル` | 2 | 1,429 | 161 | 3/3 |
| baseline | LoRA | 2 | `LoRA`・`QLoRA` | 2 | 1,842 | 216 | 3/3 |
| baseline | 確認問題 | 0 | — | 2 | 1,382 | 54 | 3/3 |
| no_must_search | 3レベル | 1 | `3レベル` | 2 | 1,381 | 154 | 3/3 |
| no_must_search | LoRA | 2 | `LoRA`・`QLoRA` | 2 | 1,794 | 172 | 3/3 |
| search_bulk | LoRA | **1** | **`LoRA QLoRA`** | 2 | **1,537** | 240 | 3/3 |
| no_lecture_ref | 3レベル | 1 | `3レベル` | 2 | 1,395 | 146 | **0/3** |
| no_lecture_ref | LoRA | 2 | `LoRA`・`QLoRA` | 2 | 1,808 | 225 | **0/3** |
| no_quiz_line | 確認問題 | 0 | — | 2 | 1,348 | 68 | 2/3 |

内容の正しさ（3レベル・どれか1つで完了・QLoRA は量子化）は、全27回で保たれていた。

1. **「必ず search_glossary」の行を消しても、検索はなくならなかった**（`no_must_search`）。6回すべてで、基準と同じ引数で `search_glossary` を呼び、回答も正しかった。変わったのは入力トークンが約48減ったこと（消した行の分）だけだった。`search_glossary` の docstring にも「答える前に使うこと」とあり、同じ指示が2か所に重なっていたためと考えられる。ただし、両方を消す条件は試していないので、docstring のおかげだとは断定できない。
2. **docstring を「まとめて」に変えると、検索は2回から1回になり、入力トークンが17%減った**（`search_bulk`）。3回とも `query="LoRA QLoRA"` の1回だけになった。一方、`requests` は2のままだった。基準でも2回の検索は1回の応答で並列に依頼されていたからだ。入力トークンが減った理由は検索結果の重複にある。基準では「LoRA」の検索で LoRA・ランク・QLoRA の3件、「QLoRA」の検索で QLoRA・LoRA の2件が返り、LoRA と QLoRA の定義を2回ずつモデルに読ませていた。まとめて検索すると、LoRA と QLoRA が1回ずつ返るだけになった。出力トークンは逆に216から240に増え、回答は長くなる傾向があった。
   - 注意：まとめた検索語でも両方見つかったのは、`search_glossary` が部分一致で探す実装だから（`"lora qlora"` の中に `lora` と `qlora` が含まれる）。完全一致で探す実装なら何も見つからない。docstring の書き方は、ツールの実装と合わせる必要がある。
3. **「回答の最後に第N回」の行を消すと、回だけを示す最後の行が消えた**（`no_lecture_ref`。基準6/6 → 0/6）。ただし、本文の中で回に触れることは残った（3レベル 2/3、LoRA 3/3）。LoRA では、用語集の定義にある「本講座の第2回演習では…」を使い、「どちらも第2回で扱う内容です」のように文中に書いた。なお基準でも、最後の行の書き方は「（第2回）」「関係する回：第2回」「第1回（関連回：第1回）」などばらばらだった。形式まで揃えたいなら、INSTRUCTIONS に書き方を指定する必要がある。
4. **「確認問題なら make_quiz」の行を消しても、make_quiz は3回とも `lecture=2` で呼ばれた**（`no_quiz_line`）。docstring の「「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う」だけで十分だった。
5. **確認問題では、6回すべてで答えを表示しなかった**（基準・`no_quiz_line` とも）。`make_quiz` は答え（用語集の定義）も返していたが、モデルは問題だけを示し、「考えてみてください」「分からなければヒントを出します」と続けた。ところが CLI は1回ごとに会話を持ち越さないので、利用者は答え合わせができない。INSTRUCTIONS の「宿題の答えそのものは書かず、考え方のヒントで導く」が確認問題にも効いた可能性があるが、未検証。

**気づき・疑問**

- 今回のモデルでは、「どのツールをいつ使うか」は INSTRUCTIONS と docstring のどちらか片方にあれば足りた。1か所消しても変わらないのは、同じ指示がもう1か所に残っているからかもしれない。どの文が効いているかを知るには、重複も含めて1か所ずつ消す必要がある。
- コストや待ち時間に効くのは、ツールの呼び出し回数（`tool_calls`）ではなく、LLM の呼び出し回数（`requests`）と、ツールの結果を含む入力トークンだった。並列に呼べる検索は `requests` を増やさない一方、検索結果の重複は入力トークンを増やす。
- 指示（INSTRUCTIONS）とツールの説明（docstring）の書き分けとしては、「何をすべきか」はどちらにも書けるが、「どう書くか（最後の行の形式）」は INSTRUCTIONS で具体的に指定しないと揃わなかった。
- 疑問：確認問題の答えをいつ見せるかは、ツールの返り値の設計（答えを返さず、別のツールで答え合わせする）で決めるべきか、指示文で決めるべきか。
- 限界：モデル1つ、各条件3回、生成設定は既定のまま。傾向の確認であり、一般的な結論とは言えない。
