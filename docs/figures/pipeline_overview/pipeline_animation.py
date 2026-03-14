"""
LangRAG Pipeline Overview Animation — Manim Scene

Generates an animated GIF showing the full newsletter generation pipeline:
  API → Parallel Orchestrator → SingleChatAnalyzer (9 stages) → Consolidation → Output

Priorities: readability first, minimal colors, no tiny text outside nodes.

Render:
  .venv/bin/python -m manim render -r 1000,500 --fps 12 --format=gif \
    docs/figures/pipeline_overview/pipeline_animation.py PipelineOverview
"""

from manim import *


# ── Colors — minimal readable palette on white ──────────────────────────────
GREEN = "#00897B"          # Primary — pipeline nodes
GREEN_LIGHT = "#4DB6AC"   # Secondary — optional/infrastructure nodes
BLUE = "#1565C0"           # Orchestration — orchestrator, aggregate, consolidation path
DARK = "#37474F"           # Entry, output, neutral
BG_COLOR = "#FFFFFF"
ARROW_COLOR = "#90A4AE"
HIGHLIGHT = "#00C853"


def make_box(label, color, width=1.4, height=0.55, font_size=16):
    rect = RoundedRectangle(
        corner_radius=0.12, width=width, height=height,
        fill_color=color, fill_opacity=0.92,
        stroke_color=color, stroke_width=1.5,
    )
    txt = Text(label, font_size=font_size, color=WHITE, weight=BOLD)
    txt.move_to(rect.get_center())
    return VGroup(rect, txt)


def make_diamond(label, color, width=1.5, height=0.7, font_size=12):
    diamond = Polygon(
        UP * height / 2, RIGHT * width / 2, DOWN * height / 2, LEFT * width / 2,
        fill_color="#E3F2FD", fill_opacity=0.4,
        stroke_color=color, stroke_width=2,
    )
    txt = Text(label, font_size=font_size, color=color, weight=BOLD)
    txt.move_to(diamond.get_center())
    return VGroup(diamond, txt)


def make_arrow(start, end, color=ARROW_COLOR):
    return Arrow(
        start, end, buff=0.08, stroke_width=2.5,
        color=color, max_tip_length_to_length_ratio=0.15,
    )


class PipelineOverview(Scene):
    def setup(self):
        self.camera.background_color = BG_COLOR

    def construct(self):
        # ── Title ───────────────────────────────────────────────────────────
        title = Text("LangRAG Pipeline", font_size=40, color=BLACK, weight=BOLD)
        title.move_to(ORIGIN)

        self.play(FadeIn(title, shift=UP * 0.3), run_time=1.0)
        self.wait(1.5)
        self.play(FadeOut(title, shift=UP * 0.5), run_time=0.6)

        # ── Row 1: API → Orchestrator → Fan-out arrows ────────────────────
        api_box = make_box("API", DARK, width=1.3, height=0.55, font_size=18)
        api_box.move_to(LEFT * 5.5 + UP * 2.2)

        orch_box = make_box("Orchestrator", BLUE, width=1.9, height=0.6, font_size=16)
        orch_box.move_to(LEFT * 3.0 + UP * 2.2)

        arrow_api_orch = make_arrow(api_box.get_right(), orch_box.get_left(), color=DARK)

        self.play(FadeIn(api_box, shift=RIGHT * 0.2), run_time=0.7)
        self.play(GrowArrow(arrow_api_orch), run_time=0.4)
        self.play(FadeIn(orch_box, shift=RIGHT * 0.2), run_time=0.7)

        # ── Row 2: SingleChatAnalyzer (9 stages) ───────────────────────────
        # Only two colors: GREEN_LIGHT for infra, GREEN for LLM-powered
        stage_configs = [
            ("Extract", GREEN_LIGHT),
            ("SLM Filter", GREEN_LIGHT),
            ("Preprocess", GREEN_LIGHT),
            ("Translate", GREEN),
            ("Separate", GREEN),
            ("Rank", GREEN),
            ("Generate", GREEN),
            ("Enrich", GREEN),
            ("Translate\nFinal", GREEN),
        ]

        # Container
        container_rect = RoundedRectangle(
            corner_radius=0.15, width=12.8, height=1.7,
            stroke_color="#B0BEC5", stroke_width=1.5,
            fill_color="#F5F5F5", fill_opacity=0.4,
        )
        container_rect.move_to(RIGHT * 0.5 + ORIGIN)

        # "Single Chat" label to the left of container
        single_chat_label = Text("Single Chat", font_size=14, color=GREEN, weight=BOLD)
        single_chat_label.next_to(container_rect, LEFT, buff=0.2)

        self.play(FadeIn(container_rect), FadeIn(single_chat_label), run_time=0.5)

        # Fan-out arrows — from orchestrator down to just above the container top
        fan_targets = [
            container_rect.get_top() + LEFT * 4.0,
            container_rect.get_top() + LEFT * 0.5,
            container_rect.get_top() + RIGHT * 3.0,
        ]
        fan_arrows = []
        for target in fan_targets:
            arrow = Arrow(
                orch_box.get_bottom(), target,
                buff=0.1, stroke_width=2, color=BLUE,
                max_tip_length_to_length_ratio=0.12,
                stroke_opacity=0.6,
            )
            fan_arrows.append(arrow)

        self.play(*[GrowArrow(a) for a in fan_arrows], run_time=0.8)
        self.wait(0.3)

        # Create stage boxes — larger text, no annotations
        stages = []
        stage_arrows = []
        x_start = -5.0
        x_step = 1.38

        for i, (name, color) in enumerate(stage_configs):
            box = make_box(name, color, width=1.22, height=0.52, font_size=13)
            box.move_to(RIGHT * (x_start + i * x_step) + ORIGIN)
            stages.append(box)

            if i > 0:
                arrow = make_arrow(
                    stages[i - 1].get_right(), box.get_left(), color=ARROW_COLOR
                )
                stage_arrows.append(arrow)

        # Animate stages in groups
        self.play(
            FadeIn(stages[0], shift=RIGHT * 0.15),
            FadeIn(stages[1], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[0]),
            run_time=0.9,
        )
        self.play(
            FadeIn(stages[2], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[1]),
            FadeIn(stages[3], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[2]),
            run_time=0.9,
        )
        self.play(
            FadeIn(stages[4], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[3]),
            FadeIn(stages[5], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[4]),
            run_time=0.9,
        )
        self.play(
            FadeIn(stages[6], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[5]),
            FadeIn(stages[7], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[6]),
            FadeIn(stages[8], shift=RIGHT * 0.15),
            GrowArrow(stage_arrows[7]),
            run_time=1.0,
        )

        # Cyclic arrow on Enrich node (index 7) — link enrichment is iterative
        enrich_box = stages[7]
        loop_arrow = CurvedArrow(
            enrich_box.get_top() + RIGHT * 0.35,
            enrich_box.get_top() + LEFT * 0.35,
            angle=-TAU * 0.65,
            stroke_width=2,
            color=GREEN,
            tip_length=0.15,
        )
        self.play(Create(loop_arrow), run_time=0.6)

        # Highlight sweep
        highlight = Rectangle(
            width=1.32, height=0.6,
            stroke_color=HIGHLIGHT, stroke_width=3,
            stroke_opacity=0.9, fill_opacity=0,
        )
        highlight.move_to(stages[0].get_center())
        self.play(FadeIn(highlight), run_time=0.3)
        for i in range(1, len(stages)):
            self.play(
                highlight.animate.move_to(stages[i].get_center()),
                run_time=0.2,
            )
        self.play(FadeOut(highlight), run_time=0.3)
        self.wait(0.5)

        # ── Row 3: Aggregate → Consolidation → Output ──────────────────────

        # "Multi Chat" label to the left of bottom row
        multi_chat_label = Text("Multi Chat", font_size=14, color=BLUE, weight=BOLD)
        multi_chat_label.move_to(LEFT * 5.5 + DOWN * 2.2)

        # Arrow from pipeline container down
        agg_box = make_box("Aggregate", BLUE, width=1.5, height=0.52, font_size=15)
        agg_box.move_to(LEFT * 3.5 + DOWN * 2.2)

        arrow_pipe_agg = Arrow(
            container_rect.get_bottom() + LEFT * 4.0,
            agg_box.get_top(),
            buff=0.08, stroke_width=2, color=BLUE,
            max_tip_length_to_length_ratio=0.15,
        )

        self.play(
            GrowArrow(arrow_pipe_agg),
            FadeIn(agg_box, shift=DOWN * 0.2),
            FadeIn(multi_chat_label),
            run_time=0.7,
        )

        # Consolidate diamond
        consolidate_diamond = make_diamond("consolidate?", BLUE, width=1.5, height=0.7, font_size=12)
        consolidate_diamond.move_to(LEFT * 1.5 + DOWN * 2.2)

        arrow_agg_diamond = make_arrow(agg_box.get_right(), consolidate_diamond.get_left(), color=BLUE)
        self.play(GrowArrow(arrow_agg_diamond), FadeIn(consolidate_diamond), run_time=0.7)

        # Consolidation path
        merge_box = make_box("Merge", BLUE, width=1.1, height=0.48, font_size=14)
        rank2_box = make_box("Rank", BLUE, width=1.1, height=0.48, font_size=14)
        gen2_box = make_box("Generate", BLUE, width=1.2, height=0.48, font_size=14)

        merge_box.move_to(RIGHT * 0.3 + DOWN * 2.2)
        rank2_box.move_to(RIGHT * 1.7 + DOWN * 2.2)
        gen2_box.move_to(RIGHT * 3.3 + DOWN * 2.2)

        # HITL as diamond (optional step)
        hitl_diamond = make_diamond("HITL", BLUE, width=1.2, height=0.6, font_size=12)
        hitl_diamond.move_to(RIGHT * 4.8 + DOWN * 2.2)

        arrow_d_merge = make_arrow(consolidate_diamond.get_right(), merge_box.get_left(), color=BLUE)
        arrow_merge_rank = make_arrow(merge_box.get_right(), rank2_box.get_left(), color=BLUE)
        arrow_rank_gen = make_arrow(rank2_box.get_right(), gen2_box.get_left(), color=BLUE)
        arrow_gen_hitl = make_arrow(gen2_box.get_right(), hitl_diamond.get_left(), color=BLUE)

        self.play(
            GrowArrow(arrow_d_merge),
            FadeIn(merge_box, shift=RIGHT * 0.15),
            run_time=0.6,
        )
        self.play(
            GrowArrow(arrow_merge_rank),
            FadeIn(rank2_box, shift=RIGHT * 0.15),
            run_time=0.5,
        )
        self.play(
            GrowArrow(arrow_rank_gen),
            FadeIn(gen2_box, shift=RIGHT * 0.15),
            run_time=0.5,
        )
        self.play(
            GrowArrow(arrow_gen_hitl),
            FadeIn(hitl_diamond),
            run_time=0.5,
        )

        # Output
        output_box = make_box("Output", DARK, width=1.4, height=0.55, font_size=16)
        output_box.move_to(RIGHT * 6.3 + DOWN * 2.2)

        arrow_hitl_out = make_arrow(hitl_diamond.get_right(), output_box.get_left(), color=DARK)

        self.play(
            GrowArrow(arrow_hitl_out),
            FadeIn(output_box, shift=RIGHT * 0.15),
            run_time=0.7,
        )

        # Final pulse
        pulse = output_box[0].copy().set_fill(opacity=0).set_stroke(color=HIGHLIGHT, width=3)
        self.play(
            pulse.animate.scale(1.3).set_stroke(opacity=0),
            run_time=0.8,
        )
        self.remove(pulse)

        self.wait(2.0)
