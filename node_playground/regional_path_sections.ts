import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// ---------------------------------------------------------------------------
// Regional path SECTION visualization (Ares Node Playground).
//
// A LaneSection border spans its leftmost-to-rightmost lane markings, so it can
// include a BIKE lane that shares the same section. Section IDs and
// extendedSections therefore cannot remove that lane after the polygon has
// already been formed.
//
// Keep one clear semantic: draw only the complete path-matching LaneSection
// outline. Do not combine it with the selected single-lane regional path;
// those two geometries naturally diverge around turns and multi-lane roads.
// The full section uses a low-alpha fill so the map remains readable.
// Geometry comes directly from planning_debug, avoiding historical MapStore ID
// mismatches as well.
// ---------------------------------------------------------------------------

export const inputs: string[] = ["/planning/planning_debug"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/regional_path_drivable_corridor";

export const config: ScriptConfig = {};

// true: translucent full-section fill; false: road-level outline only.
const FILL_SECTION = true;
const SECTION_FILL_COLOR = { r: 0.65, g: 0.2, b: 0.95, a: 0.12 };
const SECTION_EDGE_COLOR = { r: 0.78, g: 0.42, b: 1.0, a: 0.95 };
const SECTION_HEIGHT_M = 0.03;
const SECTION_EDGE_WIDTH_M = 0.25;
const Z_OFFSET_M = 0.18;
const RENDER_ORDER = 450;

type ExtendedSection = {
  elementId?: number | string;
  border?: Array<{ x: number; y: number }>;
};

const publisher = (
  messages: Record<string, Input<"/planning/planning_debug">>,
  _globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const planningInput = messages[
    "/planning/planning_debug"
  ] as Input<"/planning/planning_debug">;
  if (planningInput == null) {
    return undefined;
  }

  const { receiveTime, message } = planningInput;
  const regionalMap = (message as any)?.worldModelDebug?.regionalMapInfoDebug
    ?.regionalMap;
  const regionalPath = regionalMap?.regionalPath;
  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),
  ];

  if (regionalMap == null || regionalPath == null) {
    return { markers };
  }

  const markerZ = ((message as any)?.pose?.z ?? 0) + Z_OFFSET_M;
  const pathSectionIdSet = new Set(
    (regionalPath.pathSectionIds ?? []).map((sectionId: number | string) =>
      String(sectionId),
    ),
  );
  const extendedSections: ExtendedSection[] =
    regionalMap.extendedSections ?? [];
  const renderedSectionIds = new Set<string>();

  for (const section of extendedSections) {
    if (section?.elementId == null) {
      continue;
    }

    const sectionId = String(section.elementId);
    if (!pathSectionIdSet.has(sectionId) || renderedSectionIds.has(sectionId)) {
      continue;
    }

    const border = section.border ?? [];
    if (border.length < 3) {
      continue;
    }
    renderedSectionIds.add(sectionId);

    markers.push({
      header: { frame_id: "world", seq: 0, stamp: receiveTime },
      type: Messages.ares__VisualizationMarkerTypes.SHAPE,
      ns: "regional_path_sections",
      id: `regional_path_section_${sectionId}`,
      action: 0,
      points: border.map((point) => ({
        x: point.x,
        y: point.y,
        z: markerZ,
      })),
      pose: { position: { x: 0, y: 0, z: 0 } },
      color: SECTION_FILL_COLOR,
      fill: FILL_SECTION,
      edge: true,
      edgeColor: SECTION_EDGE_COLOR,
      edgeWidth: SECTION_EDGE_WIDTH_M,
      shapeMetadata: { height: SECTION_HEIGHT_M },
      renderOrder: RENDER_ORDER,
      // Keep Ares's native Lane/Section/Road map hover available.
      enableInteraction: false,
      hiddenHoverBubble: true,
    });
  }

  return { markers };
};

export default publisher;
