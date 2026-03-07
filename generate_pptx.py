"""Generate AgentKaizen W&B Weave Hackathon presentation as a PPTX file."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.slide import Slide
from pptx.text.text import TextFrame
from pptx.util import Inches, Pt

# ---------------------------------------------------------------------------
# Brand colors
# ---------------------------------------------------------------------------
DARK_BG = RGBColor(0x1A, 0x1A, 0x2E)
ACCENT_YELLOW = RGBColor(0xFF, 0xBE, 0x0B)
ACCENT_BLUE = RGBColor(0x3A, 0x86, 0xFF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xCC, 0xCC, 0xCC)
MEDIUM_GRAY = RGBColor(0x99, 0x99, 0x99)
LIGHT_BG = RGBColor(0xF5, 0xF5, 0xF5)  # noqa: F841 – reserved for future use
GREEN = RGBColor(0x06, 0xD6, 0xA0)
RED_ACCENT = RGBColor(0xEF, 0x47, 0x6F)

PANEL_BG = RGBColor(0x2A, 0x2A, 0x4E)
HIGHLIGHT_BG = RGBColor(0x1E, 0x3A, 0x5F)

# ---------------------------------------------------------------------------
# Layout constants (all in inches)
# ---------------------------------------------------------------------------
SLIDE_W = 13.333
SLIDE_H = 7.5

# Common padding inside rounded rect panels
PANEL_PAD_X = 0.3
PANEL_PAD_Y = 0.15

# Two-column layout
COL_W = 5.8
LEFT_X = 0.5
RIGHT_X = 6.8

BODY_FONT = "Meiryo"
CODE_FONT = "Courier New"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def add_bg(slide: Slide, color: RGBColor) -> None:
    """Fill the slide background with a solid color."""
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_text_box(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    font_size: int = 18,
    color: RGBColor = WHITE,
    bold: bool = False,
    alignment: PP_ALIGN = PP_ALIGN.LEFT,
    font_name: str = BODY_FONT,
) -> TextFrame:
    """Add a text box and return its TextFrame for further paragraph additions."""
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return tf


def add_para(
    tf: TextFrame,
    text: str,
    font_size: int = 18,
    color: RGBColor = WHITE,
    bold: bool = False,
    space_before: Pt = Pt(6),
    alignment: PP_ALIGN = PP_ALIGN.LEFT,
    font_name: str = BODY_FONT,
) -> None:
    """Append a paragraph to an existing TextFrame."""
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    if space_before:
        p.space_before = space_before


def add_rounded_rect(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    fill_color: RGBColor,
) -> None:
    """Add a borderless rounded rectangle filled with fill_color."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()


# ---------------------------------------------------------------------------
# Slide builders
# ---------------------------------------------------------------------------


def build_slide1_title(prs: Presentation) -> None:
    """Slide 1: Title."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)
    add_text_box(
        slide,
        1,
        1.5,
        11,
        1.5,
        "AgentKaizen",
        font_size=54,
        color=ACCENT_YELLOW,
        bold=True,
        alignment=PP_ALIGN.CENTER,
    )
    add_text_box(
        slide,
        1,
        3.2,
        11,
        1,
        "AIコーディングエージェントの振る舞いを、実験で改善する",
        font_size=28,
        alignment=PP_ALIGN.CENTER,
    )
    add_text_box(
        slide,
        1,
        5.0,
        11,
        0.6,
        "W&B Weave Hackathon",
        font_size=20,
        color=MEDIUM_GRAY,
        alignment=PP_ALIGN.CENTER,
    )


def build_slide2_problem(prs: Presentation) -> None:
    """Slide 2: Problem – ステアリング問題."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.4,
        11,
        0.8,
        "Problem: ステアリング問題",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )

    tf = add_text_box(
        slide,
        0.8,
        1.5,
        5.5,
        3.5,
        "コーディングエージェントの振る舞いを制御するドキュメントが多数存在:",
        font_size=18,
    )
    for doc in [
        "AGENTS.md / CLAUDE.md",
        "README.md",
        "Skills / Rules",
        "MCP Servers",
        "Config / Profile",
    ]:
        add_para(tf, f"  •  {doc}", font_size=18, color=LIGHT_GRAY, space_before=Pt(8))

    add_rounded_rect(slide, 7, 1.5, 5.5, 3.2, PANEL_BG)
    tf2 = add_text_box(
        slide,
        7.3,
        1.7,
        5,
        2.8,
        "どのドキュメントを変えれば、出力が良くなるかわからない",
        font_size=22,
        color=RED_ACCENT,
        bold=True,
    )
    add_para(tf2, "", font_size=10, space_before=Pt(12))
    for line in [
        "現状は「勘と経験」に頼っている",
        "変更の効果を定量的に測定できない",
        "ドキュメントが増えるほど特定が困難",
    ]:
        add_para(tf2, line, font_size=18, space_before=Pt(8))

    add_text_box(
        slide,
        0.8,
        5.5,
        11.5,
        1,
        '"AI is easy to demo, hard to productionize"\n'
        "— これはエージェントの設定ドキュメントにも当てはまる",
        font_size=16,
        color=MEDIUM_GRAY,
        alignment=PP_ALIGN.CENTER,
    )


def build_slide3_solution(prs: Presentation) -> None:
    """Slide 3: Solution – AgentKaizen Evaluation Loop."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.4,
        11,
        0.8,
        "Solution: AgentKaizen",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )
    add_text_box(
        slide,
        0.8,
        1.3,
        11,
        0.6,
        "ステアリングドキュメントのためのEvaluation Loop",
        font_size=22,
    )

    steps = [
        ("1. Trace", "エージェント実行を\nWeaveに記録"),
        ("2. Case生成", "実トレースから\nEval Caseを自動生成"),
        ("3. Variant定義", "ドキュメント変更を\nJSONで定義"),
        ("4. Evaluation", "同じDatasetで\nBaseline vs Variant"),
        ("5. Scoring", "Quality / Latency /\nTokenでランキング"),
        ("6. 昇格", "勝ったVariantを\n本番に反映"),
    ]

    box_w = 1.8
    box_h = 2.0
    start_x = 0.5
    y = 2.3
    gap = 0.27

    for i, (title, desc) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        color = ACCENT_BLUE if i < 5 else GREEN
        add_rounded_rect(slide, x, y, box_w, box_h, color)
        add_text_box(
            slide,
            x + 0.1,
            y + 0.2,
            box_w - 0.2,
            0.5,
            title,
            font_size=16,
            bold=True,
            alignment=PP_ALIGN.CENTER,
        )
        add_text_box(
            slide,
            x + 0.1,
            y + 0.8,
            box_w - 0.2,
            1.0,
            desc,
            font_size=13,
            alignment=PP_ALIGN.CENTER,
        )
        if i < len(steps) - 1:
            add_text_box(
                slide,
                x + box_w,
                y + 0.7,
                gap,
                0.5,
                "→",
                font_size=24,
                color=ACCENT_YELLOW,
                alignment=PP_ALIGN.CENTER,
            )

    add_text_box(
        slide,
        0.8,
        5.2,
        11,
        1,
        "「勘」から「実験」へ。Vibe Tuningを卒業する。",
        font_size=24,
        color=ACCENT_YELLOW,
        bold=True,
        alignment=PP_ALIGN.CENTER,
    )
    add_text_box(
        slide,
        0.8,
        6.0,
        11,
        0.6,
        "One-shot Runner抽象化でCodexとClaude Codeに対応。"
        "Eval/セッション分析は現在Codex中心",
        font_size=14,
        color=MEDIUM_GRAY,
        alignment=PP_ALIGN.CENTER,
    )


def build_slide4_demo(prs: Presentation) -> None:
    """Slide 4: Demo – video placeholder."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.4,
        11,
        0.8,
        "Demo",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )
    add_rounded_rect(slide, 2, 1.5, 9, 4.5, PANEL_BG)
    add_text_box(
        slide,
        2,
        2.5,
        9,
        1,
        "▶",
        font_size=72,
        color=ACCENT_YELLOW,
        alignment=PP_ALIGN.CENTER,
    )
    add_text_box(
        slide,
        2,
        4.0,
        9,
        1,
        "ここで動画を再生します（約2分）",
        font_size=24,
        alignment=PP_ALIGN.CENTER,
    )
    add_text_box(
        slide,
        2,
        4.8,
        9,
        0.6,
        "[YouTubeリンクまたは埋め込み動画]",
        font_size=16,
        color=MEDIUM_GRAY,
        alignment=PP_ALIGN.CENTER,
    )


def build_slide5_weave_features(prs: Presentation) -> None:
    """Slide 5: Weave機能の活用マップ (4 quadrants)."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.3,
        11,
        0.7,
        "Weave機能の活用マップ",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )

    y1, y2 = 1.2, 4.2
    quad_h = 2.8

    # Trace (top-left)
    add_rounded_rect(slide, LEFT_X, y1, COL_W, quad_h, PANEL_BG)
    tf = add_text_box(
        slide,
        LEFT_X + PANEL_PAD_X,
        y1 + PANEL_PAD_Y,
        COL_W - PANEL_PAD_X * 2,
        quad_h - PANEL_PAD_Y * 2,
        "Trace (トレーシング)",
        font_size=20,
        color=ACCENT_BLUE,
        bold=True,
    )
    for line in [
        ("• One-shot実行のInput/Output/メタデータ自動記録", 13, WHITE),
        ("• インタラクティブセッション取り込み・再構築", 13, WHITE),
        ("• マルチモーダル: 画像プロンプトのcontent block保持", 13, WHITE),
        ("• PIIリダクション: Weave組み込み + カスタム", 13, WHITE),
        ("  (APIキー、ローカルパス、ユーザー名の除去)", 12, LIGHT_GRAY),
    ]:
        add_para(
            tf,
            line[0],
            font_size=line[1],
            color=line[2],
            space_before=Pt(6 if line[1] == 13 else 2),
        )

    # Asset Management (top-right)
    add_rounded_rect(slide, RIGHT_X, y1, COL_W, quad_h, PANEL_BG)
    tf = add_text_box(
        slide,
        RIGHT_X + PANEL_PAD_X,
        y1 + PANEL_PAD_Y,
        COL_W - PANEL_PAD_X * 2,
        quad_h - PANEL_PAD_Y * 2,
        "Asset Management (アセット管理)",
        font_size=20,
        color=GREEN,
        bold=True,
    )
    for line in [
        ("• Dataset: JSONL Eval Case + トレースからの自動生成", 13, WHITE),
        ("• Scorer: カスタム10種 + Weave組み込み", 13, WHITE),
        ("  (ValidJSON, Pydantic)", 12, LIGHT_GRAY),
        ("• Model: CodexVariantModel (weave.Model)", 13, WHITE),
        ("  ワークスペース構成+設定の組み合わせをバージョン管理", 12, LIGHT_GRAY),
    ]:
        add_para(
            tf,
            line[0],
            font_size=line[1],
            color=line[2],
            space_before=Pt(6 if line[1] == 13 else 2),
        )

    # Offline Evaluation (bottom-left)
    add_rounded_rect(slide, LEFT_X, y2, COL_W, quad_h, PANEL_BG)
    tf = add_text_box(
        slide,
        LEFT_X + PANEL_PAD_X,
        y2 + PANEL_PAD_Y,
        COL_W - PANEL_PAD_X * 2,
        quad_h - PANEL_PAD_Y * 2,
        "Offline Evaluation (オフライン評価)",
        font_size=20,
        color=ACCENT_BLUE,
        bold=True,
    )
    for line in [
        ("• weave.Evaluationで同じDatasetに対しVariant比較", 13, WHITE),
        ("• 各Scorerの結果を横並びで確認・ランキング", 13, WHITE),
        ("• コスト・レイテンシ追跡:", 13, WHITE),
        ("  品質同等でもコスト増ならGate不合格", 12, LIGHT_GRAY),
    ]:
        add_para(
            tf,
            line[0],
            font_size=line[1],
            color=line[2],
            space_before=Pt(6 if line[1] == 13 else 2),
        )

    # Online Evaluation (bottom-right)
    add_rounded_rect(slide, RIGHT_X, y2, COL_W, quad_h, PANEL_BG)
    tf = add_text_box(
        slide,
        RIGHT_X + PANEL_PAD_X,
        y2 + PANEL_PAD_Y,
        COL_W - PANEL_PAD_X * 2,
        quad_h - PANEL_PAD_Y * 2,
        "Online Evaluation的活用",
        font_size=20,
        color=GREEN,
        bold=True,
    )
    for line in [
        ("• One-shot実行時にScorerをリアルタイム適用", 13, WHITE),
        ("• セッションのヒューリスティクスコアリング:", 13, WHITE),
        ("  ブランチ作成・テスト実行・lint実行を自動検出", 12, LIGHT_GRAY),
        ("• 今後: Weave Monitor/Guardrailとの統合", 13, MEDIUM_GRAY),
    ]:
        add_para(
            tf,
            line[0],
            font_size=line[1],
            color=line[2],
            space_before=Pt(6 if line[1] == 13 else 2),
        )


def build_slide6_custom_impl(prs: Presentation) -> None:
    """Slide 6: カスタム実装の工夫 (4 panels)."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.3,
        11,
        0.7,
        "カスタム実装の工夫",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )

    panels = [
        (
            LEFT_X,
            1.2,
            "Deterministic Scorer群 (10種)",
            ACCENT_BLUE,
            [
                "• 必須テキスト含有 / 禁止テキスト不在 / 完全一致",
                "• 文字数制限 (最小・最大) / JSON妥当性",
                "• セクション存在 / コンテンツグループ網羅",
                "• ファイルパス引用 / トークン使用量",
                "→ LLM不要の高速・安定・再現性のあるチェック",
            ],
        ),
        (
            RIGHT_X,
            1.2,
            "Variant Workspace管理",
            ACCENT_BLUE,
            [
                "• リポジトリを一時コピー → 変更適用 → 同条件で実行",
                "• JSON定義: append / prepend / replace",
                "• 外部ファイル注入にも対応",
                "→ 本番リポジトリを汚さず安全に実験",
            ],
        ),
        (
            LEFT_X,
            4.0,
            "Quality Ranking & Regression Gate",
            ACCENT_BLUE,
            [
                "• Quality Score = アクティブScorerの加重Pass率",
                "• Gate: 品質同等でもLatency/Token増 → 不合格",
                "→ 「良くなったけど遅くなった」変更を自動検出",
            ],
        ),
        (
            RIGHT_X,
            4.0,
            "セッション分析 & Case自動生成",
            ACCENT_BLUE,
            [
                "• ヒューリスティクス + 外部Judge の2層スコアリング",
                "• optimization_relevance: 次に直すべき",
                "  ドキュメントを推薦 (AGENTS/README/Skill/Config)",
                "• Weave Call History APIから過去トレース →",
                "  重複排除 → JSONL Eval Case自動生成",
            ],
        ),
    ]

    panel_h = 2.5
    for x, y, title, title_color, lines in panels:
        add_rounded_rect(slide, x, y, COL_W, panel_h, PANEL_BG)
        tf = add_text_box(
            slide,
            x + PANEL_PAD_X,
            y + 0.1,
            COL_W - PANEL_PAD_X * 2,
            panel_h - 0.2,
            title,
            font_size=18,
            color=title_color,
            bold=True,
        )
        for line in lines:
            c = (
                GREEN
                if line.startswith("→")
                else (LIGHT_GRAY if line.startswith("  ") else WHITE)
            )
            add_para(
                tf,
                line,
                font_size=13,
                color=c,
                space_before=Pt(6 if not line.startswith("  ") else 2),
            )


def build_slide7_experiment(prs: Presentation) -> None:
    """Slide 7: 実験例 – AGENTS.md日本語レスポンス制御."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.3,
        11,
        0.7,
        "実験例: AGENTS.mdで日本語レスポンス制御",
        font_size=32,
        color=ACCENT_YELLOW,
        bold=True,
    )

    # Variant JSON
    add_rounded_rect(slide, 0.5, 1.2, COL_W, 2.2, PANEL_BG)
    tf = add_text_box(
        slide,
        0.8,
        1.3,
        COL_W - 0.3,
        2.0,
        "Variant定義 (JSON)",
        font_size=16,
        color=ACCENT_BLUE,
        bold=True,
    )
    for line, color in [
        ('{ "name": "agents-japanese-response",', LIGHT_GRAY),
        ('  "edits": [{ "path": "AGENTS.md",', LIGHT_GRAY),
        ('    "mode": "append",', LIGHT_GRAY),
        ('    "text": "You must respond in Japanese."', ACCENT_YELLOW),
        ("  }] }", LIGHT_GRAY),
    ]:
        add_para(
            tf, line, font_size=13, color=color, space_before=Pt(4), font_name=CODE_FONT
        )

    # Results
    add_rounded_rect(slide, RIGHT_X, 1.2, COL_W, 2.2, PANEL_BG)
    tf2 = add_text_box(
        slide,
        RIGHT_X + PANEL_PAD_X,
        1.3,
        COL_W - PANEL_PAD_X * 2,
        2.0,
        "結果",
        font_size=16,
        color=GREEN,
        bold=True,
    )
    for line in [
        "✓ 日本語プロンプト → 日本語で回答",
        '  must_contain: "リポジトリ", "W&B Weave"',
        '✓ "Say only: ok" → "ok" (過剰適用なし)',
        "  exact_match で検証",
        '✓ "Respond in English" → 英語 (ユーザー指示優先)',
    ]:
        c = LIGHT_GRAY if line.startswith("  ") else WHITE
        add_para(
            tf2,
            line,
            font_size=13,
            color=c,
            space_before=Pt(6 if not line.startswith("  ") else 2),
        )

    # Summary
    add_rounded_rect(slide, 0.5, 3.8, 12.1, 1.6, HIGHLIGHT_BG)
    tf3 = add_text_box(
        slide,
        0.8,
        3.9,
        11.5,
        1.4,
        "Evaluation結果",
        font_size=18,
        color=ACCENT_YELLOW,
        bold=True,
    )
    for line in [
        "• Quality Score向上: VariantがBaselineを上回る",
        "• Gate Pass: Latency/Token数のリグレッションなし → 昇格可能",
        "• コントロールケースで副作用がないことも定量的に確認",
    ]:
        add_para(tf3, line, font_size=15, space_before=Pt(6))


def build_slide8_future(prs: Presentation) -> None:
    """Slide 8: 今後の展望."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide, DARK_BG)

    add_text_box(
        slide,
        0.8,
        0.3,
        11,
        0.7,
        "今後の展望",
        font_size=36,
        color=ACCENT_YELLOW,
        bold=True,
    )

    roadmap = [
        ("PyPIリリース", "pip install agentkaizen で誰でも利用可能に", "進行中"),
        ("Claude Code完全対応", "セッション分析、トークン使用量取得", "進行中"),
        ("Semantic Scorer", "LLM-as-a-Judgeで回答の意味的品質も評価", "計画中"),
        ("マルチモーダルEval拡充", "画像入力ケースの評価スコアリング", "計画中"),
        ("Online Evaluation連携", "Weave Monitor/Guardrailとの統合", "計画中"),
        ("CI/CD統合", "PRごとにドキュメント変更のEvalを自動実行", "計画中"),
    ]

    for i, (title, desc, status) in enumerate(roadmap):
        y = 1.3 + i * 0.85
        status_color = GREEN if status == "進行中" else ACCENT_BLUE
        add_rounded_rect(slide, 0.5, y, 12.1, 0.7, PANEL_BG)
        add_text_box(slide, 0.8, y + 0.08, 3.5, 0.5, title, font_size=18, bold=True)
        add_text_box(
            slide, 4.5, y + 0.08, 6.0, 0.5, desc, font_size=15, color=LIGHT_GRAY
        )
        add_text_box(
            slide,
            10.8,
            y + 0.08,
            1.5,
            0.5,
            status,
            font_size=14,
            color=status_color,
            bold=True,
            alignment=PP_ALIGN.RIGHT,
        )

    add_text_box(
        slide,
        0.8,
        6.2,
        11,
        0.8,
        "AgentKaizen: Measure changes, don't guess.\n"
        "「勘」ではなく「実験」でエージェントを改善する。",
        font_size=22,
        color=ACCENT_YELLOW,
        bold=True,
        alignment=PP_ALIGN.CENTER,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Build and save the AgentKaizen presentation PPTX."""
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    build_slide1_title(prs)
    build_slide2_problem(prs)
    build_slide3_solution(prs)
    build_slide4_demo(prs)
    build_slide5_weave_features(prs)
    build_slide6_custom_impl(prs)
    build_slide7_experiment(prs)
    build_slide8_future(prs)

    output_path = "AgentKaizen_Presentation.pptx"
    prs.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
