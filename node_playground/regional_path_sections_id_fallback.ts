import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// ---------------------------------------------------------------------------
// Full LaneSection border fallback (Ares Node Playground).
//
// Enable this topic together with regional_path_sections.ts. The primary node
// draws direct extendedSections.border geometry from planning_debug. This node
// queries Ares MapStore only for pathSectionIds whose direct border is missing.
//
// It intentionally never draws regionalPath.laneBorders. Those polygons are
// the original lane-level Regional Path, not complete LaneSections.
//
// Limits:
// - historical section IDs require the matching map version in MapStore;
// - planner-created temporary section IDs may not exist in HD map at all.
// In either case MapStore returns no geometry, which is preferable to drawing a
// lane corridor under a misleading full-section visual semantic.
//
// This fallback is deliberately disabled by default. Enable it per layout by
// setting the Ares global variable below to the boolean value true. Keeping the
// switch here (rather than in regional_path_sections.ts) means direct
// extendedSections geometry remains available without opting into MapStore.
// ---------------------------------------------------------------------------

export const inputs: string[] = ["/planning/planning_debug", "/pose"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/regional_path_sections_id_fallback";

export const config: ScriptConfig = {
  executeScriptWhenAnyMessageReceived: true,
};

const SECTION_FILL_COLOR = { r: 0.65, g: 0.2, b: 0.95, a: 0.12 };
const SECTION_EDGE_COLOR = { r: 0.78, g: 0.42, b: 1.0, a: 0.95 };
const FILL_SECTION = true;
const SECTION_HEIGHT_M = 0.03;
const SECTION_EDGE_WIDTH_M = 0.25;
const Z_OFFSET_M = 0.18;
const RENDER_ORDER = 449;
const ENABLE_FALLBACK_GLOBAL_VARIABLE =
  "assist_vlm_enable_regional_path_section_id_fallback";
const DEFAULT_ENABLE_MAPSTORE_ID_FALLBACK = false;

type RegionalPathFallbackGlobalVariables = GlobalVariables & {
  assist_vlm_enable_regional_path_section_id_fallback?: boolean;
};

type PlanningInput = Input<"/planning/planning_debug">;
type PoseInput = Input<"/pose">;

type ExtendedSection = {
  elementId?: number | string;
  border?: Array<{ x: number; y: number }>;
};

// voyager_map_elements/PathArray's generated declaration contains the ROS
// fields only. Ares consumes these additional MapStore query fields at runtime.
type LaneSectionQueryMarker = {
  header: Messages.std_msgs__Header;
  ns: string;
  id: string;
  type: Messages.ares__VisualizationMarkerTypes;
  action: number;
  color: Messages.std_msgs__ColorRGBA;
  pose: {
    position: { x: number; y: number; z: number };
    orientation: { x: number; y: number; z: number; w: number };
  };
  scale: { x: number; y: number; z: number };
  renderOrder: number;
  metadata: {
    isAresMarker: true;
    sceneCenter: {
      position: { x: number; y: number; z: number };
      orientation: { x: number; y: number; z: number; w: number };
    };
    queryProp: {
      name: "LaneSection";
      value: number;
    };
    poseZ: number;
    height: number;
    fill: boolean;
    edge: true;
    edgeColor: Messages.std_msgs__ColorRGBA;
    edgeWidth: number;
    enableInteraction: false;
  };
};

let latestPlanningInput: PlanningInput | undefined;
let latestPoseInput: PoseInput | undefined;

const hasDrawableBorder = (section: ExtendedSection): boolean =>
  section.elementId != null &&
  (section.border?.length ?? 0) >= 3 &&
  section.border!.every(
    (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
  );

const publisher = (
  messages: Record<string, PlanningInput | PoseInput>,
  globalVars: GlobalVariables,
): Messages.voyager_map_elements__PathArray | undefined => {
  const planningInput = messages["/planning/planning_debug"] as
    | PlanningInput
    | undefined;
  const poseInput = messages["/pose"] as PoseInput | undefined;

  if (planningInput != null) {
    latestPlanningInput = planningInput;
  }
  if (poseInput != null) {
    latestPoseInput = poseInput;
  }
  if (latestPlanningInput == null) {
    return undefined;
  }

  const planning = latestPlanningInput.message;
  const pose = latestPoseInput?.message ?? planning.pose;
  const receiveTime =
    planningInput?.receiveTime ??
    poseInput?.receiveTime ??
    latestPlanningInput.receiveTime;

  // PathArray requires marker[0] to be a normal delete marker. Its legacy
  // consumer reads ns directly even for DELETE_ALL.
  const markers: Array<
    LaneSectionQueryMarker | Messages.ares__VisualizationMarker
  > = [
    {
      ...createDeleteCurrentTopicMarkers(receiveTime),
      ns: "",
    },
  ];

  const fallbackEnabled =
    (globalVars as RegionalPathFallbackGlobalVariables)[
      ENABLE_FALLBACK_GLOBAL_VARIABLE
    ] ?? DEFAULT_ENABLE_MAPSTORE_ID_FALLBACK;
  if (fallbackEnabled !== true) {
    // Publish DELETE_ALL so disabling the flag also clears markers emitted
    // while it was enabled; do not leave stale fallback geometry on screen.
    return { markers } as unknown as Messages.voyager_map_elements__PathArray;
  }

  const regionalMap = (planning as any)?.worldModelDebug?.regionalMapInfoDebug
    ?.regionalMap;
  const regionalPath = regionalMap?.regionalPath;
  if (pose == null || regionalPath == null) {
    return { markers } as unknown as Messages.voyager_map_elements__PathArray;
  }

  const directSectionIds = new Set<string>();
  const extendedSections: ExtendedSection[] =
    regionalMap.extendedSections ?? [];
  for (const section of extendedSections) {
    if (hasDrawableBorder(section)) {
      directSectionIds.add(String(section.elementId!));
    }
  }

  // Preserve path order while removing duplicates and IDs already rendered by
  // the primary direct-border node.
  const unresolvedSectionIds: Array<{ key: string; value: number }> = [];
  const seenSectionIds = new Set<string>();
  for (const rawSectionId of regionalPath.pathSectionIds ?? []) {
    if (rawSectionId == null) {
      continue;
    }
    const key = String(rawSectionId);
    if (seenSectionIds.has(key) || directSectionIds.has(key)) {
      continue;
    }
    seenSectionIds.add(key);

    const value =
      typeof rawSectionId === "number"
        ? rawSectionId
        : Number(rawSectionId);
    if (!Number.isSafeInteger(value)) {
      continue;
    }
    unresolvedSectionIds.push({ key, value });
  }

  const halfYaw = pose.yaw * 0.5;
  const sceneOrientation = {
    x: 0,
    y: 0,
    z: Math.sin(halfYaw),
    w: Math.cos(halfYaw),
  };
  const scenePosition = { x: pose.x, y: pose.y, z: pose.z };
  const markerZ = pose.z + Z_OFFSET_M;

  for (const { key, value } of unresolvedSectionIds) {
    markers.push({
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      ns: "regional_path_sections_id_fallback",
      id: `regional_path_section_id_fallback_${key}`,
      type: Messages.ares__VisualizationMarkerTypes.SHAPE_EXTRUDE,
      action: 0,
      color: SECTION_FILL_COLOR,
      pose: {
        position: { x: 0, y: 0, z: 0 },
        orientation: { x: 0, y: 0, z: 0, w: 1 },
      },
      scale: { x: 1, y: 1, z: 1 },
      renderOrder: RENDER_ORDER,
      metadata: {
        isAresMarker: true,
        sceneCenter: {
          position: scenePosition,
          orientation: sceneOrientation,
        },
        queryProp: {
          name: "LaneSection",
          value,
        },
        poseZ: markerZ,
        height: SECTION_HEIGHT_M,
        fill: FILL_SECTION,
        edge: true,
        edgeColor: SECTION_EDGE_COLOR,
        edgeWidth: SECTION_EDGE_WIDTH_M,
        enableInteraction: false,
      },
    });
  }

  return { markers } as unknown as Messages.voyager_map_elements__PathArray;
};

export default publisher;
