import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// ---------------------------------------------------------------------------
// Regional Path visualization (road bag).
//
// Built-in Ares topics (closed-source studio nodes, not in this repo):
//   /studio_node/routing/regional_routing/regional_path_lane_sequence
//   /studio_node/routing/regional_routing/regional_path_lane_id
//
// Geometry is already filled onboard into planning_debug (see
// regional_map_generator.cpp): each path lane's border polygon is written to
//   planning_debug.worldModelDebug.regionalMapInfoDebug.regionalMap
//     .regionalPath.laneBorders
//
// This script re-draws the same borders so the colour can be changed freely.
// Turn OFF the built-in regional_routing topics in the 3D topic tree when using
// this, otherwise you will see two overlays.
// ---------------------------------------------------------------------------

export const inputs: string[] = ["/planning/planning_debug"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/regional_path";

export const config: ScriptConfig = {};

// >>> change colour here <<<
const PATH_COLOR = { r: 0.65, g: 0.2, b: 0.95, a: 0.95 }; // purple
// Line thickness in metres (built-in is thin corridor edges).
const LINE_WIDTH = 0.35;
// Lift above map / road surface. pose.z is ground altitude.
const Z_OFFSET = 0.3;
const RENDER_ORDER = 500;

type Point3 = { x: number; y: number; z: number };

const publisher = (
  messages: Record<string, Input<"/planning/planning_debug">>,
  _globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const debugInput = messages[
    "/planning/planning_debug"
  ] as Input<"/planning/planning_debug">;
  if (debugInput == null) {
    return undefined;
  }

  const { receiveTime, message } = debugInput;
  const regionalPath = (message as any)?.worldModelDebug?.regionalMapInfoDebug
    ?.regionalMap?.regionalPath;
  if (regionalPath == null) {
    return undefined;
  }

  const laneBorders: Array<{ points?: Array<{ x: number; y: number }> }> =
    regionalPath.laneBorders ?? [];
  if (laneBorders.length === 0) {
    return {
      markers: [createDeleteCurrentTopicMarkers(receiveTime)],
    };
  }

  const poseZ = ((message as any)?.pose?.z ?? 0) + Z_OFFSET;
  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),
  ];

  for (let i = 0; i < laneBorders.length; i++) {
    const poly = laneBorders[i];
    const pts = poly?.points;
    if (pts == null || pts.length < 2) {
      continue;
    }

    // Full lane border polygon: left side forward + right side back → looks
    // like the dual red corridor edges in the built-in regional path viz.
    const points: Point3[] = pts.map((p) => ({
      x: p.x,
      y: p.y,
      z: poseZ,
    }));
    // Explicit close (do not rely solely on lineMetadata.closed).
    const first = points[0];
    const last = points[points.length - 1];
    if (first.x !== last.x || first.y !== last.y) {
      points.push({ ...first });
    }

    markers.push({
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: `regional_path_lane_border_${i}`,
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points,
      color: PATH_COLOR,
      renderOrder: RENDER_ORDER,
      lineMetadata: {
        lineWidth: LINE_WIDTH,
        closed: false,
      },
    });
  }

  return { markers };
};

export default publisher;
