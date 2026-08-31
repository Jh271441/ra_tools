import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
  getIntentionPlanDebug,
} from "@ares-utils";

// ---------------------------------------------------------------------------
// Custom path_solution visualization.
//
// Built-in Ares topic (closed-source studio node, no Export Code icon):
//   /studio_node/planning/path_generator/primitives/path_smoother/path_solution
//   source: vitruvian adaptor/planning-new/path-solution.ts
//
// Data path (same as built-in):
//   planning_debug
//     → getIntentionPlanDebug(behaviorReasonerDebug, globalVars)
//     → pathPlannerDebug.pathSmootherDebug.pathSolverDebug.iterations
//     → last iteration.solution.xs[{xPos,yPos}, ...]
//
// Render as a SHAPE_EXTRUDE ribbon, not LINE_STRIP. Ares LINE_STRIP often
// composites over other topics, so a thick stroke paints over ego.
// Stacking (z / renderOrder):
//   reference_path (yellow)  z+0.15 / order 0
//   this path_solution       z+0.25 / order 180
//   ego_pose (pink)          z+~2.0 / order 1000
//
// Paste this into Node Playground, then turn OFF the built-in path_solution
// leaf in the 3D topic tree so the two overlays do not stack.
// ---------------------------------------------------------------------------

export const inputs: string[] = ["/planning/planning_debug"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/path_solution";

export const config: ScriptConfig = {};

// >>> change colour / width here <<<
// Avoid ego hot-pink {1.0, 0.2, 0.75} and the yellow trajectory in this layout.
const PATH_COLOR = { r: 0.15, g: 0.85, b: 0.95, a: 0.7 }; // cyan
const LINE_WIDTH = 1.5;
// Sit above yellow reference_path (z+0.15) and still under ego (z+~2.0).
const Z_OFFSET = 0.25;
const EXTRUDE_HEIGHT = 0.04;
const RENDER_ORDER = 180;

type Point2 = { x: number; y: number };

type SolutionPoint = {
  xPos?: number;
  yPos?: number;
};

const flattenContour = (contour: Point2[]): Float32Array => {
  const flattened = new Float32Array(contour.length * 3);
  for (let i = 0; i < contour.length; i++) {
    flattened[i * 3] = contour[i].x;
    flattened[i * 3 + 1] = contour[i].y;
    flattened[i * 3 + 2] = 0;
  }
  return flattened;
};

const polylineToRibbon = (points: Point2[], halfWidth: number): Point2[] => {
  const left: Point2[] = [];
  const right: Point2[] = [];
  for (let i = 0; i < points.length; i++) {
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(points.length - 1, i + 1)];
    let dx = next.x - prev.x;
    let dy = next.y - prev.y;
    const length = Math.hypot(dx, dy);
    if (length < 1e-6) {
      dx = 1;
      dy = 0;
    } else {
      dx /= length;
      dy /= length;
    }
    const nx = -dy * halfWidth;
    const ny = dx * halfWidth;
    left.push({ x: points[i].x + nx, y: points[i].y + ny });
    right.push({ x: points[i].x - nx, y: points[i].y - ny });
  }
  return left.concat(right.reverse());
};

const publisher = (
  messages: Record<string, Input<"/planning/planning_debug">>,
  globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const debugInput = messages[
    "/planning/planning_debug"
  ] as Input<"/planning/planning_debug">;
  if (debugInput == null) {
    return undefined;
  }

  const { receiveTime, message } = debugInput;
  const pose = (message as any)?.pose;
  if (pose == null) {
    return {
      markers: [createDeleteCurrentTopicMarkers(receiveTime)],
    };
  }

  const intentionPlanDebug = getIntentionPlanDebug(
    (message as any)?.behaviorReasonerDebug,
    globalVars,
  );
  const iterations =
    intentionPlanDebug?.pathPlannerDebug?.pathSmootherDebug?.pathSolverDebug
      ?.iterations;
  if (iterations == null || iterations.length === 0) {
    return {
      markers: [createDeleteCurrentTopicMarkers(receiveTime)],
    };
  }

  const solutionPoints: SolutionPoint[] =
    iterations[iterations.length - 1]?.solution?.xs ?? [];
  const points: Point2[] = [];
  for (let i = 0; i < solutionPoints.length; i++) {
    const pt = solutionPoints[i];
    if (pt?.xPos == null || pt?.yPos == null) {
      continue;
    }
    points.push({ x: pt.xPos, y: pt.yPos });
  }
  if (points.length < 2) {
    return {
      markers: [createDeleteCurrentTopicMarkers(receiveTime)],
    };
  }

  const ribbon = polylineToRibbon(points, LINE_WIDTH / 2);
  const groundZ = (pose.z ?? 0) + Z_OFFSET;

  return {
    markers: [
      createDeleteCurrentTopicMarkers(receiveTime),
      {
        header: { frame_id: "world", stamp: receiveTime, seq: 0 },
        id: "path_smoother_path_solution_ground",
        type: Messages.ares__VisualizationMarkerTypes.SHAPE_EXTRUDE,
        action: 0,
        pose: {
          position: { x: 0, y: 0, z: groundZ },
          orientation: { x: 0, y: 0, z: 0, w: 1 },
        },
        scale: { x: 1, y: 1, z: 1 },
        flattenedPoints: flattenContour(ribbon),
        color: PATH_COLOR,
        fill: true,
        edge: false,
        renderOrder: RENDER_ORDER,
        shapeMetadata: { height: EXTRUDE_HEIGHT },
      },
    ],
  };
};

export default publisher;
