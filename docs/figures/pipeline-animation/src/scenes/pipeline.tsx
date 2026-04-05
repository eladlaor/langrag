import {makeScene2D, Rect, Txt, Line, Circle} from '@motion-canvas/2d';
import {
  all,
  createRef,
  delay,
  easeInOutCubic,
  easeOutCubic,
  linear,
  sequence,
  Vector2,
  waitFor,
} from '@motion-canvas/core';
import {COLORS} from '../components/PipelineNode';

// ──────────────────────────────────────────────────
// Layout constants
// ──────────────────────────────────────────────────

const VIEW_W = 1920;
const VIEW_H = 1080;

// Row Y positions
const ROW_TOP = -340;
const ROW_MID = 20;
const ROW_BOT = 370;

// Single chat container — wider to fit 10 nodes
const CONTAINER_X = 80;
const CONTAINER_Y = ROW_MID;
const CONTAINER_W = 1780;
const CONTAINER_H = 200;

// Stage spacing inside container (10 stages now)
const STAGE_W = 148;
const STAGE_H = 72;
const STAGE_GAP = 170;
const STAGE_START_X = CONTAINER_X - CONTAINER_W / 2 + 95;

// Bottom row — 9 nodes
const BOT_NODE_W = 165;
const BOT_NODE_H = 66;
const BOT_GAP = 185;
const BOT_START_X = -660;

// Top row node sizes
const NODE_W = 185;
const NODE_H = 66;

// ──────────────────────────────────────────────────
// Pipeline data
// ──────────────────────────────────────────────────

interface StageData {
  label: string;
  color: string;
}

// 10 stages — no final Translate (it moves to bottom row as shared last step)
const PIPELINE_STAGES: StageData[] = [
  {label: 'Extract\nMessages', color: COLORS.TEAL},
  {label: 'SLM\nFilter', color: COLORS.TEAL},
  {label: 'Extract\nImages', color: COLORS.TEAL},
  {label: 'Preprocess\nData', color: COLORS.TEAL},
  {label: 'Normalize\nto English', color: COLORS.PURPLE},
  {label: 'Separate\nDiscussions', color: COLORS.PURPLE},
  {label: 'Rank\nDiscussions', color: COLORS.PURPLE},
  {label: 'Associate\nImages', color: COLORS.PURPLE},
  {label: 'Generate\nSummary', color: COLORS.PURPLE},
  {label: 'Link\nEnrichment', color: COLORS.PURPLE},
];

interface BottomNode {
  label: string;
  color: string;
  isCircle?: boolean;
}

// Bottom row: 9 nodes — consolidation pipeline
const BOTTOM_NODES: BottomNode[] = [
  {label: 'Aggregate\nCross-Chat', color: COLORS.BLUE},
  {label: 'Merge Similar\nDiscussions', color: COLORS.BLUE},
  {label: 'ReRank', color: COLORS.BLUE},
  {label: 'Apply\nMMR', color: COLORS.BLUE},
  {label: 'Generate\nConsolidated', color: COLORS.BLUE},
  {label: 'Human in\nthe Loop', color: COLORS.BLUE, isCircle: true},
  {label: 'Translate', color: COLORS.PURPLE},
  {label: 'Structure\nFormats', color: COLORS.PURPLE},
  {label: 'Send to\nEmail / Hook', color: COLORS.AMBER},
];

// ──────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────

function stageX(i: number): number {
  return STAGE_START_X + i * STAGE_GAP;
}

function botX(i: number): number {
  return BOT_START_X + i * BOT_GAP;
}

function glowOf(color: string): string {
  return color + '60';
}

// ──────────────────────────────────────────────────
// Scene
// ──────────────────────────────────────────────────

export default makeScene2D(function* (view) {
  // Set background
  view.fill(COLORS.BG);

  // ── Title ──
  const titleRef = createRef<Txt>();
  view.add(
    <Txt
      ref={titleRef}
      text={'LangRAG'}
      fontSize={64}
      fontFamily={'Inter, system-ui, sans-serif'}
      fontWeight={700}
      fill={COLORS.TEXT}
      opacity={0}
      y={0}
    />,
  );

  // Fade in title
  yield* titleRef().opacity(1, 0.4, easeOutCubic);
  yield* waitFor(0.5);
  // Move title up and shrink to become header
  yield* all(
    titleRef().y(-470, 0.5, easeInOutCubic),
    titleRef().fontSize(42, 0.5, easeInOutCubic),
    titleRef().opacity(0.7, 0.5, easeInOutCubic),
  );

  // ── Row 1: API → Orchestrator ──
  const apiRef = createRef<Rect>();
  const orchRef = createRef<Rect>();
  const apiEdgeRef = createRef<Line>();

  const apiX = -650;
  const orchX = -400;

  view.add(
    <>
      {/* API node */}
      <Rect
        ref={apiRef}
        x={apiX}
        y={ROW_TOP}
        width={NODE_W}
        height={NODE_H}
        radius={8}
        fill={COLORS.AMBER + '30'}
        stroke={COLORS.AMBER}
        lineWidth={1.5}
        opacity={0}
        scale={0.6}
        shadowColor={glowOf(COLORS.AMBER)}
        shadowBlur={12}
      >
        <Txt
          text={'API\nRequest'}
          fontSize={22}
          fontFamily={'Inter, system-ui, sans-serif'}
          fontWeight={600}
          fill={COLORS.TEXT}
          textAlign={'center'}
        />
      </Rect>

      {/* Orchestrator node */}
      <Rect
        ref={orchRef}
        x={orchX}
        y={ROW_TOP}
        width={220}
        height={NODE_H}
        radius={8}
        fill={COLORS.BLUE + '30'}
        stroke={COLORS.BLUE}
        lineWidth={1.5}
        opacity={0}
        scale={0.6}
        shadowColor={glowOf(COLORS.BLUE)}
        shadowBlur={12}
      >
        <Txt
          text={'Orchestrator'}
          fontSize={24}
          fontFamily={'Inter, system-ui, sans-serif'}
          fontWeight={600}
          fill={COLORS.TEXT}
        />
      </Rect>

      {/* API → Orchestrator edge */}
      <Line
        ref={apiEdgeRef}
        points={[
          new Vector2(apiX + NODE_W / 2, ROW_TOP),
          new Vector2(orchX - 100, ROW_TOP),
        ]}
        stroke={COLORS.EDGE}
        lineWidth={2}
        end={0}
        endArrow
        arrowSize={10}
        lineCap={'round'}
      />
    </>,
  );

  // Animate API in
  yield* all(
    apiRef().opacity(1, 0.3, easeOutCubic),
    apiRef().scale(1, 0.4, easeOutCubic),
  );

  // Edge draws
  yield* apiEdgeRef().end(1, 0.3, easeInOutCubic);

  // Orchestrator in
  yield* all(
    orchRef().opacity(1, 0.3, easeOutCubic),
    orchRef().scale(1, 0.4, easeOutCubic),
  );
  yield* waitFor(0.4);

  // ── Fan-out arrows from Orchestrator to container ──
  const fanEdges: ReturnType<typeof createRef<Line>>[] = [];
  const fanTargetX = CONTAINER_X - CONTAINER_W / 2 + 110;
  const fanSpread = 40; // slight vertical spread at arrival

  for (let fi = 0; fi < 3; fi++) {
    const ref = createRef<Line>();
    fanEdges.push(ref);

    const targetY = CONTAINER_Y - CONTAINER_H / 2 + (fi - 1) * fanSpread;
    const midY = ROW_TOP + 80 + fi * 15;

    view.add(
      <Line
        ref={ref}
        points={[
          new Vector2(orchX, ROW_TOP + NODE_H / 2),
          new Vector2(orchX + (fi - 1) * 30, midY),
          new Vector2(fanTargetX, targetY),
        ]}
        stroke={COLORS.BLUE + '80'}
        lineWidth={2.5}
        end={0}
        endArrow
        arrowSize={10}
        lineCap={'round'}
        lineJoin={'round'}
      />,
    );
  }

  yield* sequence(
    0.1,
    ...fanEdges.map((ref) => ref().end(1, 0.4, easeInOutCubic)),
  );

  // ── Container: Single Chat Analyzer ──
  const containerRef = createRef<Rect>();
  const containerLabel = createRef<Txt>();

  view.add(
    <>
      <Rect
        ref={containerRef}
        x={CONTAINER_X}
        y={CONTAINER_Y}
        width={CONTAINER_W}
        height={CONTAINER_H}
        radius={12}
        fill={COLORS.CONTAINER_BG}
        stroke={COLORS.CONTAINER_BORDER}
        lineWidth={1}
        opacity={0}
      />
      <Txt
        ref={containerLabel}
        text={'Single Chat Analyzer'}
        fontSize={24}
        fontFamily={'Inter, system-ui, sans-serif'}
        fontWeight={600}
        fill={COLORS.TEXT + '80'}
        x={CONTAINER_X - CONTAINER_W / 2 + 120}
        y={CONTAINER_Y - CONTAINER_H / 2 - 20}
        opacity={0}
      />
    </>,
  );

  yield* all(
    containerRef().opacity(1, 0.3, easeOutCubic),
    containerLabel().opacity(1, 0.3, easeOutCubic),
  );
  yield* waitFor(0.5);

  // ── Pipeline stages (10 nodes) ──
  const stageRefs: ReturnType<typeof createRef<Rect>>[] = [];
  const stageEdgeRefs: ReturnType<typeof createRef<Line>>[] = [];

  for (let i = 0; i < PIPELINE_STAGES.length; i++) {
    const s = PIPELINE_STAGES[i];
    const ref = createRef<Rect>();
    stageRefs.push(ref);

    view.add(
      <Rect
        ref={ref}
        x={stageX(i)}
        y={CONTAINER_Y}
        width={STAGE_W}
        height={STAGE_H}
        radius={6}
        fill={s.color + '30'}
        stroke={s.color}
        lineWidth={1.2}
        opacity={0}
        scale={0.6}
        shadowColor={glowOf(s.color)}
        shadowBlur={8}
      >
        <Txt
          text={s.label}
          fontSize={18}
          fontFamily={'Inter, system-ui, sans-serif'}
          fontWeight={600}
          fill={COLORS.TEXT}
          textAlign={'center'}
        />
      </Rect>,
    );

    // Edge to previous stage
    if (i > 0) {
      const eRef = createRef<Line>();
      stageEdgeRefs.push(eRef);
      view.add(
        <Line
          ref={eRef}
          points={[
            new Vector2(stageX(i - 1) + STAGE_W / 2, CONTAINER_Y),
            new Vector2(stageX(i) - STAGE_W / 2, CONTAINER_Y),
          ]}
          stroke={COLORS.EDGE}
          lineWidth={1.5}
          end={0}
          endArrow
          arrowSize={8}
          lineCap={'round'}
        />,
      );
    }
  }

  // Animate stages in groups with edges
  // Group 1: Extract, SLM Filter, Extract Images
  yield* all(
    ...stageRefs.slice(0, 3).map((ref) =>
      all(
        ref().opacity(1, 0.25, easeOutCubic),
        ref().scale(1, 0.35, easeOutCubic),
      ),
    ),
  );
  yield* all(
    ...stageEdgeRefs.slice(0, 2).map((ref, i) =>
      delay(i * 0.06, ref().end(1, 0.2, easeInOutCubic)),
    ),
  );
  yield* waitFor(0.3);

  // Group 2: Preprocess → Associate Images
  yield* all(
    ...stageRefs.slice(3, 8).map((ref, i) =>
      delay(
        i * 0.06,
        all(
          ref().opacity(1, 0.25, easeOutCubic),
          ref().scale(1, 0.35, easeOutCubic),
        ),
      ),
    ),
  );
  yield* all(
    ...stageEdgeRefs.slice(2, 7).map((ref, i) =>
      delay(i * 0.06, ref().end(1, 0.2, easeInOutCubic)),
    ),
  );

  // Group 3: Generate Summary, Link Enrichment
  yield* all(
    ...stageRefs.slice(8, 10).map((ref, i) =>
      delay(
        i * 0.06,
        all(
          ref().opacity(1, 0.25, easeOutCubic),
          ref().scale(1, 0.35, easeOutCubic),
        ),
      ),
    ),
  );
  yield* all(
    ...stageEdgeRefs.slice(7, 9).map((ref, i) =>
      delay(i * 0.06, ref().end(1, 0.2, easeInOutCubic)),
    ),
  );

  // ── Cyclic arrow on Link Enrichment (index 9) ──
  const linkLoopRef = createRef<Line>();
  const linkX = stageX(9);
  const loopRadius = 36;

  view.add(
    <Line
      ref={linkLoopRef}
      points={[
        new Vector2(linkX + 28, CONTAINER_Y - STAGE_H / 2),
        new Vector2(linkX + 28, CONTAINER_Y - STAGE_H / 2 - loopRadius),
        new Vector2(linkX - 28, CONTAINER_Y - STAGE_H / 2 - loopRadius),
        new Vector2(linkX - 28, CONTAINER_Y - STAGE_H / 2),
      ]}
      stroke={COLORS.PURPLE + '90'}
      lineWidth={2}
      end={0}
      endArrow
      arrowSize={7}
      lineCap={'round'}
      lineJoin={'round'}
      radius={14}
    />,
  );

  yield* linkLoopRef().end(1, 0.4, easeInOutCubic);
  yield* waitFor(0.5);

  // ── Data pulse through pipeline ──
  const pulseRef = createRef<Circle>();
  view.add(
    <Circle
      ref={pulseRef}
      width={12}
      height={12}
      fill={COLORS.GREEN}
      opacity={0}
      shadowColor={COLORS.GREEN}
      shadowBlur={18}
      x={stageX(0)}
      y={CONTAINER_Y}
    />,
  );

  // Build pulse path
  const pulsePath: Vector2[] = PIPELINE_STAGES.map((_, i) =>
    new Vector2(stageX(i), CONTAINER_Y),
  );

  yield* pulseRef().opacity(1, 0.15, easeOutCubic);
  for (let i = 1; i < pulsePath.length; i++) {
    yield* pulseRef().position(pulsePath[i], 0.25, linear);
  }
  yield* pulseRef().opacity(0, 0.15, easeOutCubic);
  yield* waitFor(0.6);

  // ── Bottom row: Multi-chat path ──
  const multiLabel = createRef<Txt>();
  view.add(
    <Txt
      ref={multiLabel}
      text={'Multi Chat Consolidation'}
      fontSize={24}
      fontFamily={'Inter, system-ui, sans-serif'}
      fontWeight={600}
      fill={COLORS.TEXT + '80'}
      x={BOT_START_X - 120}
      y={ROW_BOT - 55}
      opacity={0}
    />,
  );
  yield* multiLabel().opacity(1, 0.25, easeOutCubic);

  // Bottom nodes — mix of Rect and Circle (for HITL)
  const botRefs: ReturnType<typeof createRef<Rect | Circle>>[] = [];
  const botEdgeRefs: ReturnType<typeof createRef<Line>>[] = [];
  const CIRCLE_R = 56; // radius for HITL circle

  function botNodeWidth(idx: number): number {
    return BOTTOM_NODES[idx].isCircle ? CIRCLE_R * 2 : BOT_NODE_W;
  }

  for (let i = 0; i < BOTTOM_NODES.length; i++) {
    const n = BOTTOM_NODES[i];

    if (n.isCircle) {
      // HITL as circle
      const ref = createRef<Circle>();
      botRefs.push(ref as any);
      view.add(
        <Circle
          ref={ref}
          x={botX(i)}
          y={ROW_BOT}
          width={CIRCLE_R * 2}
          height={CIRCLE_R * 2}
          fill={n.color + '30'}
          stroke={n.color}
          lineWidth={1.5}
          opacity={0}
          scale={0.6}
          shadowColor={glowOf(n.color)}
          shadowBlur={12}
        >
          <Txt
            text={n.label}
            fontSize={15}
            fontFamily={'Inter, system-ui, sans-serif'}
            fontWeight={600}
            fill={COLORS.TEXT}
            textAlign={'center'}
          />
        </Circle>,
      );
    } else {
      // Regular rect node
      const ref = createRef<Rect>();
      botRefs.push(ref as any);
      view.add(
        <Rect
          ref={ref}
          x={botX(i)}
          y={ROW_BOT}
          width={BOT_NODE_W}
          height={BOT_NODE_H}
          radius={8}
          fill={n.color + '30'}
          stroke={n.color}
          lineWidth={1.5}
          opacity={0}
          scale={0.6}
          shadowColor={glowOf(n.color)}
          shadowBlur={12}
        >
          <Txt
            text={n.label}
            fontSize={18}
            fontFamily={'Inter, system-ui, sans-serif'}
            fontWeight={600}
            fill={COLORS.TEXT}
            textAlign={'center'}
          />
        </Rect>,
      );
    }

    if (i > 0) {
      const eRef = createRef<Line>();
      botEdgeRefs.push(eRef);

      const prevHalf = botNodeWidth(i - 1) / 2;
      const curHalf = botNodeWidth(i) / 2;

      view.add(
        <Line
          ref={eRef}
          points={[
            new Vector2(botX(i - 1) + prevHalf, ROW_BOT),
            new Vector2(botX(i) - curHalf, ROW_BOT),
          ]}
          stroke={COLORS.EDGE}
          lineWidth={2}
          end={0}
          endArrow
          arrowSize={9}
          lineCap={'round'}
        />,
      );
    }
  }

  // ── Cyclic arrow on HITL (index 5) ──
  const hitlLoopRef = createRef<Line>();
  const hitlX = botX(5);
  const hitlLoopR = 38;

  view.add(
    <Line
      ref={hitlLoopRef}
      points={[
        new Vector2(hitlX + 24, ROW_BOT - CIRCLE_R),
        new Vector2(hitlX + 24, ROW_BOT - CIRCLE_R - hitlLoopR),
        new Vector2(hitlX - 24, ROW_BOT - CIRCLE_R - hitlLoopR),
        new Vector2(hitlX - 24, ROW_BOT - CIRCLE_R),
      ]}
      stroke={COLORS.BLUE + '90'}
      lineWidth={2}
      end={0}
      endArrow
      arrowSize={7}
      lineCap={'round'}
      lineJoin={'round'}
      radius={14}
    />,
  );

  // Orchestrator → Aggregate Cross-Chat connection
  const orchToAggRef = createRef<Line>();
  view.add(
    <Line
      ref={orchToAggRef}
      points={[
        new Vector2(orchX, ROW_TOP + NODE_H / 2),
        new Vector2(orchX, ROW_BOT - 100),
        new Vector2(botX(0), ROW_BOT - 40),
        new Vector2(botX(0), ROW_BOT - BOT_NODE_H / 2),
      ]}
      stroke={COLORS.BLUE + '60'}
      lineWidth={1.5}
      end={0}
      endArrow
      arrowSize={8}
      lineCap={'round'}
      lineJoin={'round'}
      radius={24}
    />,
  );

  yield* orchToAggRef().end(1, 0.5, easeInOutCubic);

  // Animate bottom nodes progressively
  for (let i = 0; i < BOTTOM_NODES.length; i++) {
    yield* all(
      botRefs[i]().opacity(1, 0.2, easeOutCubic),
      botRefs[i]().scale(1, 0.3, easeOutCubic),
    );
    if (i > 0 && botEdgeRefs[i - 1]) {
      yield* botEdgeRefs[i - 1]().end(1, 0.2, easeInOutCubic);
    }
  }

  // Animate HITL self-loop
  yield* hitlLoopRef().end(1, 0.4, easeInOutCubic);

  // ── Final pulse on Output ──
  const outputIdx = BOTTOM_NODES.length - 1;
  yield* all(
    botRefs[outputIdx]().shadowBlur(30, 0.4, easeInOutCubic),
    botRefs[outputIdx]().scale(1.08, 0.4, easeInOutCubic),
  );
  yield* all(
    botRefs[outputIdx]().shadowBlur(12, 0.3, easeInOutCubic),
    botRefs[outputIdx]().scale(1, 0.3, easeInOutCubic),
  );

  // Hold final view
  yield* waitFor(3.0);
});
