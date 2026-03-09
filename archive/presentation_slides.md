# AgentKaizen - W&B Weave Hackathon Presentation
# スライド原稿 (Google Slides用) + Speaker Notes

---

## Slide 1: タイトル

**AgentKaizen**
AIコーディングエージェントの振る舞いを、実験で改善する

W&B Weave Hackathon

[著者名]

---

## Slide 2: Problem - 課題

**AIコーディングエージェントの「ステアリング問題」**

Codex、Claude Codeなどのコーディングエージェントには、振る舞いを制御する多数のドキュメントがある：

- AGENTS.md / CLAUDE.md
- README.md
- Skills / Rules
- MCP Servers
- Config / Profile

**課題: どのドキュメントを変えれば、出力が良くなるかわからない**

現状は「勘と経験」に頼っている。変更のたびに手動で確認し、効果があったか判断できない。
ドキュメントが増えるほど、どこを直すべきか特定が困難になる。

**"AI is easy to demo, hard to productionize" — これはエージェントの設定ドキュメントにも当てはまる。**

Speaker Notes:
- W&Bが掲げる課題「AI is easy to demo, hard to productionize」はコーディングエージェントの設定にも当てはまる
- ドキュメントを変えたつもりが逆効果だったり、一部のケースで副作用が出るリスクがある
- 例: AGENTS.mdに「日本語で回答せよ」と書いたら、英語で指示されたケースでも日本語で返してしまうかも?
- Eval-Driven / Eval-Centricなアプローチが必要

---

## Slide 3: Solution - AgentKaizenとは

**AgentKaizen: ステアリングドキュメントのためのEvaluation Loop**

W&B Weaveを活用し、ドキュメント変更を「実験」として扱い、定量的に比較する

**ワークフロー:**
1. **Trace**: エージェント実行をWeaveに記録
2. **Case生成**: 実トレースからEval Caseを自動生成
3. **Variant定義**: ドキュメント変更をJSON形式で定義
4. **Offline Evaluation**: 同じDatasetでBaseline vs Variantを比較
5. **Scoring & Ranking**: Quality / Latency / Token Usageで自動判定
6. **昇格**: 勝ったVariantを本番ドキュメントに反映

**「勘」から「実験」へ。Vibe Tuningを卒業する。**

Speaker Notes:
- 核心は「ドキュメントチューニングをEvaluation Loopに変える」こと
- WeaveのTrace → Dataset → Model → Evaluation → Scorerの一連の機能を繋げて活用
- One-shot Runner抽象化でCodexとClaude Codeに対応。Eval/セッション分析は現在Codex中心
- 「Vibe Tuningからの卒業」= Eval-Centricなドキュメント改善

---

## Slide 4: Demo

**End-to-End デモ (約2分)**

ここで動画を再生します。

[動画を埋め込みまたはYouTubeリンク]

Speaker Notes:
- 動画を再生する。約2分。
- 実際のCodex CLI実行からWeaveへのトレース送信までの一連の流れを見せる
- 日本語レスポンス実験: AGENTS.mdに「日本語で回答」を追加したVariantと、Baselineを同じプロンプトで比較
- Weave UIでper-caseの出力差分を確認できる

---

## Slide 5: Weave機能の活用マップ

**AgentKaizenが活用するWeave機能一覧**

### Trace (トレーシング)
- One-shot実行: エージェントのInput/Output/メタデータ/コスト/レイテンシを自動記録
- インタラクティブセッション取り込み: Codexの会話セッションを再構築してTrace化
- **マルチモーダル対応**: 画像プロンプトのcontent blockを構造的に保持・可視化
- **PIIリダクション**: Weave組み込みPIIリダクション + カスタム (APIキー、ローカルパス、ユーザー名) のハイブリッド方式

### Asset Management (アセット管理)
- **Dataset**: JSONL形式のEval Caseスイート。Weave Call History APIから実トレースを使ったCase自動生成にも対応
- **Scorer**: 10個のカスタムScorer + Weave組み込みScorer (ValidJSON, Pydantic) を登録・管理
- **Model**: 各Variantを`weave.Model`継承の`CodexVariantModel`としてバージョン管理。ワークスペース構成・モデル設定・ドキュメント変更の組み合わせがバージョンとなる

### Offline Evaluation (オフライン評価)
- `weave.Evaluation`で同じDatasetに対し、Baseline vs 複数Variantを実行・比較
- 各Scorerの結果を横並びで確認。Quality Scoreでランキング
- **コスト・レイテンシ追跡**: トークン使用量・レイテンシを自動集計し、品質同等でもコスト増ならGate不合格

### Online Evaluation的な活用 (ガードレール)
- One-shot実行時にScorerをリアルタイム適用し、出力品質をチェック
- インタラクティブセッションのヒューリスティクスコアリング: ブランチ作成・テスト実行・lint実行などワークフロー準拠を自動検出

Speaker Notes:
- Weaveの公式機能分類に沿って説明。Trace / Asset Management / Offline Eval / Online Evalの4軸
- Model Versioning: LLMアプリの「モデル」= APIモデル + プロンプト + ツール + 設定の組み合わせ。AgentKaizenでは「リポジトリのドキュメント構成 + Agent設定」がバージョン
- Weaveだけが提供するModel Versioningを、ドキュメントVariant管理に応用している点は差別化ポイント
- PIIリダクション: Weave組み込みのPresidio統合だけでは不十分（ローカルファイルパス、セッション固有データ）なので、カスタムレイヤーで補完
- Online Evaluation: 厳密なGuardrail/Monitorではないが、One-shot実行時のリアルタイムスコアリングとセッション分析がそれに近い役割

---

## Slide 6: カスタム実装の工夫

**Weaveの上に構築した独自機能**

### 1. Deterministic Scorer群 (10種)
構造的・構文的チェックに特化したカスタムScorer:
- 必須テキスト含有 / 禁止テキスト不在 / 完全一致
- 文字数制限 (最小・最大) / JSON妥当性
- セクション存在 / コンテンツグループ網羅
- ファイルパス引用 / トークン使用量

→ Weave組み込みScorer (ValidJSON, Pydantic) と組み合わせてScorerパイプラインを構成

### 2. Variant Workspace管理
- リポジトリを一時コピー → ドキュメント変更を適用 → 同条件で実行
- VariantはJSON定義: ファイル編集モード (append/prepend/replace) + 外部ファイル注入

### 3. Quality Ranking & Regression Gate
- Quality Score = アクティブなScorerの加重Pass率
- Gate判定: 品質が同等 (delta ≤ threshold) でもLatencyやToken数がリグレッションなら不合格
- → 「良くなったけど遅くなった」変更を自動検出

### 4. セッション分析 & 最適化推薦
- ヒューリスティクス + 外部Codex Judge (optional) の2層スコアリング
- `optimization_relevance`: 次にどのドキュメント (AGENTS.md / README / Skill / Config) を改善すべきかを推薦

### 5. Eval Case自動生成
- Weave Call History APIから過去トレースを取得・フィルタ
- プロンプト/出力を抽出 → 重複排除 → JSONL Eval Caseとして出力
- → 実際の使用パターンからDatasetを継続的に拡充

Speaker Notes:
- カスタムScorerはLLMを呼ばない決定的チェック。高速・安定・再現性がある
- Variant Workspaceはサンドボックス的な仕組み。本番リポジトリを汚さずに実験できる
- Gate判定の狙い: 品質が微差なら、効率の良い方を選ぶ。品質が明確に上がれば多少のコスト増は許容
- optimization_relevance: セッション分析の結果から「次にどこを直すべきか」を提案。人間の判断を支援
- Case自動生成: Weaveに蓄積されたトレースを再利用してDatasetを育てる。実使用パターンからの回帰テスト

---

## Slide 7: 実験例 - AGENTS.mdで日本語レスポンス制御

**実験: 「日本語で回答せよ」をAGENTS.mdに追加したら?**

Variant定義 (`evals/variants/example_agents_japanese_response.json`):
```json
{
  "name": "agents-japanese-response",
  "edits": [{
    "path": "AGENTS.md",
    "mode": "append",
    "text": "\nYou must respond in Japanese.\n"
  }]
}
```

Eval Cases (`evals/cases/language-steering.jsonl`) から抜粋:

| プロンプト (実際のCase) | Baseline | Variant |
|---|---|---|
| "Reply in one sentence: what does this repository do?" | 英語で回答 | **日本語で回答** (must_contain: リポジトリ, W&B Weave) |
| "Say only: ok" | "ok" | "ok" **(過剰適用なし, exact_match)** |
| "Respond in English with one sentence: what does this repository do?" | 英語で回答 | 英語で回答 **(ユーザー指示優先, must_contain: repository, CLI)** |

結果:
- Variant側のQuality Scoreが向上 (日本語プロンプトで日本語回答)
- コントロールケースで過剰適用がないことを確認
- Gate Pass: Latency/Token数のリグレッションなし → **昇格可能**

Speaker Notes:
- この実験はREADMEでも「推奨初回デモ」として紹介している
- JSON一つでVariantを定義できるシンプルさがポイント
- コントロールケースの重要性: 「Say only: ok」で過剰に日本語化しないこと、英語指示時にユーザー意図を優先することを検証
- Weave UIで各ケースの出力を1行ずつ確認できる

---

## Slide 8: 今後の展望

**Next Steps**

- **PyPIリリース**: `pip install agentkaizen` で誰でも利用可能に (進行中)
- **Claude Code完全対応**: セッション分析、トークン使用量取得 (進行中)
- **Semantic Scorer**: LLM-as-a-Judgeで回答の意味的品質も評価
- **マルチモーダルEval拡充**: 画像入力ケースの評価スコアリング
- **Online Evaluation連携**: Weave Monitor/Guardrailとの統合で本番環境の継続監視
- **CI/CD統合**: PRごとにドキュメント変更のEvalを自動実行

**AgentKaizen: Measure changes, don't guess.**
**「勘」ではなく「実験」でエージェントを改善する。**

Speaker Notes:
- PyPIリリースとClaude Code対応は既にコードベースにある (半完成)
- Semantic Scorer: 現在のScorerは構造的チェック中心。LLM-as-a-Judgeで「回答の有用性」も測りたい
- Online Evaluation: 現在はOffline中心だが、WeaveのMonitor/Guardrail機能と連携すれば本番でも継続評価可能
- 最終ビジョン: PRでドキュメントを変更 → CIでEvalが自動実行 → 品質が上がった変更だけマージ
- 「Eval-Centric」「Eval-Driven」なドキュメント改善をCLIツールで実現する
