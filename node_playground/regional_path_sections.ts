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
// border. Never draw regionalPath.laneBorders: that field is the selected
// lane-level Regional Path and has a different meaning. If pathSectionIds is
// absent, laneBorders may only be used internally to select overlapping full
// extendedSections borders; the published geometry remains section-level.
// The full section uses a low-alpha fill so the map remains readable.
// Geometry comes directly from planning_debug, avoiding historical MapStore ID
// mismatches as well.
//
// Missing direct geometry is handled by the companion Node Playground script
// regional_path_sections_id_fallback.ts. It queries MapStore only for path
// section IDs that do not already have a drawable extendedSections border.
// That companion fallback is default-off and requires the boolean Ares global
// variable assist_vlm_enable_regional_path_section_id_fallback=true.
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

type Point2 = { x: number; y: number };

type LaneBorder = {
  points?: Point2[];
};

const hasDrawableBorder = (section: ExtendedSection): boolean =>
  (section.border?.length ?? 0) >= 3 &&
  section.border!.every(
    (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
  );

const pointInPolygon = (point: Point2, polygon: Point2[]): boolean => {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i];
    const b = polygon[j];
    const crosses =
      a.y > point.y !== b.y > point.y &&
      point.x <
        ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x;
    if (crosses) {
      inside = !inside;
    }
  }
  return inside;
};

// laneBorders is used only as a selector when pathSectionIds is unavailable.
// Pull samples slightly toward the lane polygon's average point so shared
// section boundaries do not select a neighbouring section by mere contact.
const createInteriorSamples = (points: Point2[]): Point2[] => {
  const validPoints = points.filter(
    (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
  );
  if (validPoints.length < 3) {
    return [];
  }

  const center = validPoints.reduce(
    (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
    { x: 0, y: 0 },
  );
  center.x /= validPoints.length;
  center.y /= validPoints.length;

  const sampleStep = Math.max(1, Math.floor(validPoints.length / 12));
  const samples: Point2[] = [center];
  for (let i = 0; i < validPoints.length; i += sampleStep) {
    samples.push({
      x: validPoints[i].x * 0.9 + center.x * 0.1,
      y: validPoints[i].y * 0.9 + center.y * 0.1,
    });
  }
  return samples;
};

const sectionOverlapsRegionalPath = (
  sectionBorder: Point2[],
  regionalPathSamples: Point2[],
): boolean =>
  regionalPathSamples.some((sample) =>
    pointInPolygon(sample, sectionBorder),
  );

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
    (regionalPath.pathSectionIds ?? [])
      .filter((sectionId: number | string | null | undefined) => sectionId != null)
      .map((sectionId: number | string) => String(sectionId)),
  );
  const extendedSections: ExtendedSection[] =
    regionalMap.extendedSections ?? [];
  const laneBorders: LaneBorder[] = regionalPath.laneBorders ?? [];
  const useGeometrySelectionFallback =
    pathSectionIdSet.size === 0 && laneBorders.length > 0;
  const regionalPathSamples = useGeometrySelectionFallback
    ? laneBorders.reduce<Point2[]>(
        (samples, laneBorder) => [
          ...samples,
          ...createInteriorSamples(laneBorder.points ?? []),
        ],
        [],
      )
    : [];
  const renderedSectionIds = new Set<string>();

  for (
    let sectionIndex = 0;
    sectionIndex < extendedSections.length;
    sectionIndex++
  ) {
    const section = extendedSections[sectionIndex];
    if (!hasDrawableBorder(section)) {
      continue;
    }

    const sectionId =
      section.elementId == null ? undefined : String(section.elementId);
    const border = section.border!;
    const selectedById =
      sectionId != null && pathSectionIdSet.has(sectionId);
    const selectedByGeometry =
      useGeometrySelectionFallback &&
      sectionOverlapsRegionalPath(border, regionalPathSamples);
    if (!selectedById && !selectedByGeometry) {
      continue;
    }

    const markerKey = sectionId ?? `geometry_${sectionIndex}`;
    if (renderedSectionIds.has(markerKey)) {
      continue;
    }
    renderedSectionIds.add(markerKey);

    markers.push({
      header: { frame_id: "world", seq: 0, stamp: receiveTime },
      type: Messages.ares__VisualizationMarkerTypes.SHAPE,
      ns: "regional_path_sections",
      id: `regional_path_section_${markerKey}`,
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
