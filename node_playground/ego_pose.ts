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

// Visual styling — thicker stroke only; bbox size stays at car size.
const BOX_COLOR = { r: 1.0, g: 0.2, b: 0.75, a: 1.0 }; // hot pink
const ARROW_COLOR = { r: 1.0, g: 0.2, b: 0.75, a: 1.0 }; // same pink
const ORIGIN_COLOR = { r: 1.0, g: 0.9, b: 0.1, a: 1.0 };
const BOX_LINE_WIDTH = 0.45;
const ARROW_LINE_WIDTH = 0.5;
// Shaft from geometric centre; longer tip for clear heading.
const ARROW_LENGTH_M = HALF_LENGTH_M + 3.5; // ~5.8 m tip from centre
const ARROW_HEAD_LENGTH_M = 1.2;
const ARROW_HEAD_HALF_WIDTH_M = 0.55;

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

  // Heading arrow: centre -> forward.
  const arrowTipLocalX = ARROW_LENGTH_M;
  const headBaseLocalX = arrowTipLocalX - ARROW_HEAD_LENGTH_M;

  const center = toWorld(0, 0, poseX, poseY, cosYaw, sinYaw, markerZ);
  const arrowTip = toWorld(
    arrowTipLocalX,
    0,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );
  const headLeft = toWorld(
    headBaseLocalX,
    ARROW_HEAD_HALF_WIDTH_M,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );
  const headRight = toWorld(
    headBaseLocalX,
    -ARROW_HEAD_HALF_WIDTH_M,
    poseX,
    poseY,
    cosYaw,
    sinYaw,
    markerZ,
  );

  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),

    // 1) Ego bounding-box outline
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_bbox",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: boxPoints,
      color: BOX_COLOR,
      renderOrder: RENDER_ORDER,
      lineMetadata: {
        lineWidth: BOX_LINE_WIDTH,
        closed: false, // already closed by duplicating first point
      },
    },

    // 2) Heading shaft
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_heading_shaft",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: [center, arrowTip],
      color: ARROW_COLOR,
      renderOrder: RENDER_ORDER + 1,
      lineMetadata: {
        lineWidth: ARROW_LINE_WIDTH,
        closed: false,
      },
    },

    // 3) Heading arrow head (V)
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_heading_head",
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points: [headLeft, arrowTip, headRight],
      color: ARROW_COLOR,
      renderOrder: RENDER_ORDER + 1,
      lineMetadata: {
        lineWidth: ARROW_LINE_WIDTH,
        closed: false,
      },
    },

    // 4) Pose origin (geometric centre of mesh)
    {
      header: { frame_id: "world", stamp: receiveTime, seq: 0 },
      id: "ego_pose_origin",
      type: Messages.ares__VisualizationMarkerTypes.POINTS,
      action: 0,
      points: [center],
      color: ORIGIN_COLOR,
      renderOrder: RENDER_ORDER + 2,
      pointMetadata: {
        radius: 0.25,
        sizeAttenuation: true,
      },
    },
  ];

  return { markers };
};

export default publisher;
