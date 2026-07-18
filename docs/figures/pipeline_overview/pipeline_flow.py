"""
LangRAG newsletter-generation pipeline — diagram generator.

Two nodes differ from the pipeline as currently implemented in src/graphs/:
  1. "Parse Media Content" sits one node before Preprocess: the vision LLM
     transcribes each media-message and writes the parsed text back INTO the
     message stream, so it participates in ranking like any other text.
  2. There is no post-rank "Associate Images" join — with media content inlined
     at ingestion, it flows through Separate/Rank naturally and needs no join.

Renders the 1920x1080 pipeline diagram used in the project README. The animated
counterpart (pipeline_overview.gif) is built from the Motion Canvas project in
docs/figures/pipeline-animation/ and must be kept in sync with this diagram.

Run:  python docs/figures/pipeline_overview/pipeline_flow.py
Out:  docs/figures/pipeline_overview/pipeline_flow.png
"""

import os
from PIL import Image, ImageDraw, ImageFont

# ── Palette ────────────────────────────
BG = (10, 10, 26)
BAND = (15, 23, 42)
WHITE = (248, 250, 252)
TITLE = (129, 130, 139)
SECTION = (129, 130, 139)

TEAL_FILL, TEAL_BORDER = (12, 62, 84), (9, 122, 148)          # infra / ingestion
PURPLE_FILL, PURPLE_BORDER = (46, 40, 93), (92, 66, 169)      # LLM-powered
BLUE_FILL, BLUE_BORDER = (24, 43, 88), (60, 90, 170)          # orchestration
ORANGE_FILL, ORANGE_BORDER = (77, 52, 22), (196, 140, 55)     # entry / output
ARROW = (60, 90, 150)

# ── Geometry (sampled) ──────────────────────────────────────────────────────
W, H = 1920, 1080
NODE_W, NODE_H, RADIUS = 147, 71, 10
GAP = 23
ROW1_CY = 199          # API / Orchestrator
ROW2_CY = 560          # Single Chat Analyzer
ROW3_CY = 909          # Multi Chat Consolidation
ROW2_X0 = 171          # first node left edge
BAND_TOP, BAND_BOT = 484, 660

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
F_TITLE = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans-Bold.ttf", 40)
F_SECTION = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 22)
F_NODE = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 16)
F_SMALL = ImageFont.truetype(f"{FONT_DIR}/DejaVuSans.ttf", 13)


def node(d, cx, cy, lines, fill, border, w=NODE_W, h=NODE_H, font=F_NODE):
    x0, y0 = cx - w // 2, cy - h // 2
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=RADIUS,
                        fill=fill, outline=border, width=2)
    n = len(lines)
    line_h = 19
    total = n * line_h
    ty = cy - total / 2 + line_h / 2
    for ln in lines:
        d.text((cx, ty), ln, font=font, fill=WHITE, anchor="mm")
        ty += line_h


def arrow(d, x1, y1, x2, y2, color=ARROW, width=2):
    d.line([x1, y1, x2, y2], fill=color, width=width)
    # simple triangular head pointing right
    if x2 > x1:
        d.polygon([(x2, y2), (x2 - 8, y2 - 5), (x2 - 8, y2 + 5)], fill=color)


def self_loop(d, cx, top_y, color=None, w=NODE_W, h=NODE_H):
    """Rounded self-loop arc rising from a node's top edge and returning to it,
    matching the loop-back arcs on Link Enrichment / Human-in-the-Loop."""
    color = color or ARROW
    xr = cx + w * 0.28   # riser up on the right
    xl = cx - w * 0.28   # return down on the left (arrowhead lands here)
    arc_top = top_y - 34
    r = 12
    # right riser
    d.line([xr, top_y, xr, arc_top + r], fill=color, width=2)
    # top-right corner
    d.arc([xr - 2 * r, arc_top, xr, arc_top + 2 * r], 270, 360, fill=color, width=2)
    # top span
    d.line([xl + r, arc_top, xr - r, arc_top], fill=color, width=2)
    # top-left corner
    d.arc([xl, arc_top, xl + 2 * r, arc_top + 2 * r], 180, 270, fill=color, width=2)
    # left return
    d.line([xl, arc_top + r, xl, top_y - 6], fill=color, width=2)
    # arrowhead into the node top
    d.polygon([(xl, top_y), (xl - 5, top_y - 8), (xl + 5, top_y - 8)], fill=color)


def circle_node(d, cx, cy, lines, fill, border, diam=None, font=F_SMALL):
    diam = diam or NODE_H + 12
    r = diam // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=border, width=2)
    n = len(lines)
    line_h = 17
    ty = cy - n * line_h / 2 + line_h / 2
    for ln in lines:
        d.text((cx, ty), ln, font=font, fill=WHITE, anchor="mm")
        ty += line_h


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Title
    d.text((W // 2, 68), "LangRAG", font=F_TITLE, fill=TITLE, anchor="mm")

    # ── Row 1: API -> Orchestrator ──────────────────────────────────────────
    node(d, 309, ROW1_CY, ["API", "Request"], ORANGE_FILL, ORANGE_BORDER)
    node(d, 560, ROW1_CY, ["Orchestrator"], BLUE_FILL, BLUE_BORDER)
    arrow(d, 309 + NODE_W // 2, ROW1_CY, 560 - NODE_W // 2, ROW1_CY)

    # Orchestrator fan-out (schematic) to both bands
    d.line([560, ROW1_CY + NODE_H // 2, 300, BAND_TOP - 20], fill=ARROW, width=2)
    d.line([560, ROW1_CY + NODE_H // 2, 300, ROW3_CY - NODE_H // 2 - 20], fill=ARROW, width=2)

    # ── Single Chat Analyzer band ───────────────────────────────────────────
    d.rounded_rectangle([149, BAND_TOP, 1900, BAND_BOT], radius=14, fill=BAND)
    d.text((160, 439), "Single Chat Analyzer", font=F_SECTION, fill=SECTION, anchor="lm")

    # 9 nodes — media content is parsed to text here, so no post-rank image join.
    # (fill, border, [lines])  teal = ingestion/infra, purple = LLM-powered
    row2 = [
        (TEAL_FILL, TEAL_BORDER, ["Extract", "Messages"]),
        (TEAL_FILL, TEAL_BORDER, ["SLM", "Labeling"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Parse Media", "Content"]),   # vision -> inline text
        (TEAL_FILL, TEAL_BORDER, ["Preprocess", "Data"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Normalize", "to English"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Separate", "Discussions"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Rank", "Discussions"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Generate", "Summary"]),
        (PURPLE_FILL, PURPLE_BORDER, ["Link", "Enrichment"]),
    ]
    step = NODE_W + GAP
    centers = []
    for i, (fill, border, lines) in enumerate(row2):
        cx = ROW2_X0 + NODE_W // 2 + i * step
        centers.append(cx)
        node(d, cx, ROW2_CY, lines, fill, border)
        if i > 0:
            arrow(d, centers[i - 1] + NODE_W // 2, ROW2_CY, cx - NODE_W // 2, ROW2_CY)

    # Link Enrichment (last node) loops back on itself — iterative link resolution
    self_loop(d, centers[-1], ROW2_CY - NODE_H // 2, color=PURPLE_BORDER)

    # annotation clarifying why this node sits before Preprocess
    d.text((centers[2], ROW2_CY + NODE_H // 2 + 16),
           "media → text, before ranking", font=F_SMALL, fill=(120, 130, 160), anchor="mm")

    # ── Multi Chat Consolidation band ───────────────────────────────────────
    d.text((60, 854), "Multi Chat Consolidation", font=F_SECTION, fill=SECTION, anchor="lm")
    # "shape" flags: "circle" renders HITL as a circle with a self-loop.
    row3 = [
        (BLUE_FILL, BLUE_BORDER, ["Aggregate", "Cross-Chat"], "rect"),
        (BLUE_FILL, BLUE_BORDER, ["Merge Similar", "Discussions"], "rect"),
        (BLUE_FILL, BLUE_BORDER, ["ReRank"], "rect"),
        (BLUE_FILL, BLUE_BORDER, ["Apply", "MMR"], "rect"),
        (BLUE_FILL, BLUE_BORDER, ["Generate", "Consolidated"], "rect"),
        (BLUE_FILL, BLUE_BORDER, ["Human in", "the Loop"], "circle"),
        (PURPLE_FILL, PURPLE_BORDER, ["Translate"], "rect"),
        (PURPLE_FILL, PURPLE_BORDER, ["Structure", "Formats"], "rect"),
        (ORANGE_FILL, ORANGE_BORDER, ["Send to", "Email / Hook"], "rect"),
    ]
    r3x0 = 216
    prev = None
    for i, (fill, border, lines, shape) in enumerate(row3):
        cx = r3x0 + NODE_W // 2 + i * step
        if shape == "circle":
            diam = NODE_H + 12
            circle_node(d, cx, ROW3_CY, lines, fill, border, diam=diam)
            self_loop(d, cx, ROW3_CY - diam // 2, color=BLUE_BORDER, w=diam)
            half = diam // 2
        else:
            node(d, cx, ROW3_CY, lines, fill, border)
            half = NODE_W // 2
        if prev is not None:
            arrow(d, prev[0] + prev[1], ROW3_CY, cx - half, ROW3_CY)
        prev = (cx, half)

    out = os.path.join(os.path.dirname(__file__), "pipeline_flow.png")
    img.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
