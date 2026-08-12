import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// Road bag: localization pose only.
export const inputs: string[] = ["/pose"];

// 3DPanel topics must start with /studio_node/
export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/ego_pose";

export const config: ScriptConfig = {};

// ---------------------------------------------------------------------------
// Gen4 production car (GAC_A2T) dimensions.
// Source: voyager/onboard/common/vehicle_model/config/
//   axle_rectangular_shape_measurement_gac_a2t.conf
//
// Alignment note:
//   Bicycle-model / feature extractors use rear-axle as origin, but the Ares
//   3D ego mesh is placed with /pose at the vehicle geometric centre. Drawing
//   the footprint about the rear axle left the pink box ~1.5 m forward of the
//   mesh (geometry_center_to_rear_axle ≈ 1.46 m). Match the mesh: ±L/2, ±W/2.
// Local vehicle frame: +x forward along yaw, +y left.
// ---------------------------------------------------------------------------
// Physical Gen4 footprint (do not inflate beyond car size).
const EGO_LENGTH_M = 4.54;
const EGO_WIDTH_M = 1.87;
const HALF_LENGTH_M = EGO_LENGTH_M / 2;
const HALF_WIDTH_M = EGO_WIDTH_M / 2;

// Visual semantics:
// - filled hot-pink rectangle: current ego footprint at /pose;
// - centered white arrow inside the footprint: ego heading only, not a future
//   path or a distance prediction.
const BOX_COLOR = { r: 1.0, g: 0.2, b: 0.75, a: 1.0 }; // hot pink
const BOX_FILL_COLOR = { r: 1.0, g: 0.2, b: 0.75, a: 0.58 };
const HEADING_COLOR = { r: 1.0, g: 1.0, b: 1.0, a: 1.0 };
const BOX_LINE_WIDTH = 0.35;
const HEADING_LINE_WIDTH = 0.18;
const BOX_FILL_HEIGHT_M = 0.04;

// Keep the complete arrow inside the footprint and centered on the vehicle's
// longitudinal axis. The tip stops before the front bumper.
const HEADING_SHAFT_START_LOCAL_X = -EGO_LENGTH_M * 0.18;
const HEADING_TIP_LOCAL_X = HALF_LENGTH_M - EGO_LENGTH_M * 0.12;
const HEADING_HEAD_LENGTH_M = EGO_LENGTH_M * 0.18;
const HEADING_HEAD_HALF_WIDTH_M = HALF_WIDTH_M * 0.35;

// pose.z is ground altitude. Lift markers above the roof so the mesh does not
// occlude the outline.
const EGO_HEIGHT_M = 1.6;
const Z_ABOVE_ROOF_M = 0.4;
const MARKER_Z = EGO_HEIGHT_M + Z_ABOVE_ROOF_M; // ~2.0 m above ground
const RENDER_ORDER = 1000;

type Point3 = { x: number; y: number; z: number };

const toWorld = (
  localX: number,
  localY: number,
  poseX: number,
  poseY: number,
  cosYaw: number,
  sinYaw: number,
  z: number,
): Point3 => ({
  x: localX * cosYaw - localY * sinYaw + poseX,
  y: localX * sinYaw + localY * cosYaw + poseY,
  z,
});

const publisher = (
  messages: Record<string, Input<"/pose">>,
  _globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const poseInput = messages["/pose"] as Input<"/pose">;
  if (poseInput == null) {
    return undefined;
  }

  const { receiveTime, message: pose } = poseInput;
  const poseX = pose.x;
  const poseY = pose.y;
  const markerZ = pose.z + MARKER_Z;
  const yaw = pose.yaw;
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);

  // Footprint about geometric centre at /pose (matches Ares ego mesh).
  // Explicitly re-append the first point so the polyline always closes.
  const localCorners: Array<[number, number]> = [
    [-HALF_LENGTH_M, HALF_WIDTH_M], // rear-left
    [-HALF_LENGTH_M, -HALF_WIDTH_M], // rear-right
    [HALF_LENGTH_M, -HALF_WIDTH_M], // front-right
    [HALF_LENGTH_M, HALF_WIDTH_M], // front-left
    [-HALF_LENGTH_M, HALF_WIDTH_M], // close
  ];
  const boxPoints = localCorners.map(([lx, ly]) =>
    toWorld(lx, ly, poseX, poseY, cosYaw, sinYaw, markerZ),
  );
  const boxFillPoints = new Float32Array(4 * 3);
  for (let index = 0; index < 4; index++) {
    const point = boxPoints[index]!;
    boxFillPoints[index * 3] = point.x;
    boxFillPoints[index * 3 + 1] = point.y;
    boxFillPoints[index * 3 + 2] = 0.0;
  }

  const headingShaftStart = toWorld(
    HEADING_SHAFT_START_LOCAL_X,
    0,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );
  const headingHeadBaseLocalX =
    HEADING_TIP_LOCAL_X - HEADING_HEAD_LENGTH_M;
  const headingHeadLeft = toWorld(
    headingHeadBaseLocalX,
    HEADING_HEAD_HALF_WIDTH_M,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );
  const headingTip = toWorld(
    HEADING_TIP_LOCAL_X,
    0,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );
  const headingHeadRight = toWorld(
    headingHeadBaseLocalX,
    -HEADING_HEAD_HALF_WIDTH_M,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );

  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),

    // 1) Semi-transparent ego footprint fill. It intentionally sits just
    // below the outline so the border and heading remain crisp.
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_bbox_fill",
      type: Messages.ares__VisualizationMarkerTypes.SHAPE_EXTRUDE,
      action: 0,
      pose: {
        position: { x: 0, y: 0, z: markerZ - BOX_FILL_HEIGHT_M },
        orientation: { x: 0, y: 0, z: 0, w: 1 },
      },
      scale: { x: 1, y: 1, z: 1 },
      flattenedPoints: boxFillPoints,
      color: BOX_FILL_COLOR,
      fill: true,
      edge: false,
      renderOrder: RENDER_ORDER,
      shapeMetadata: { height: BOX_FILL_HEIGHT_M },
    },

    // 2) Ego bounding-box outline
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_bbox",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: boxPoints,
      color: BOX_COLOR,
      renderOrder: RENDER_ORDER + 1,
      lineMetadata: {
        lineWidth: BOX_LINE_WIDTH,
        closed: false, // already closed by duplicating first point
      },
    },

    // 3) Centered heading shaft
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_heading_shaft",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: [headingShaftStart, headingTip],
      color: HEADING_COLOR,
      renderOrder: RENDER_ORDER + 2,
      lineMetadata: {
        lineWidth: HEADING_LINE_WIDTH,
        closed: false,
      },
    },

    // 4) V-shaped arrow head
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_heading_head",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: [headingHeadLeft, headingTip, headingHeadRight],
      color: HEADING_COLOR,
      renderOrder: RENDER_ORDER + 2,
      lineMetadata: {
        lineWidth: HEADING_LINE_WIDTH,
        closed: false,
      },
    },
  ];

  return { markers };
};

export default publisher;
