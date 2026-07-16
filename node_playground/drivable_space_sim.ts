import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// Simulation-only version. Load this instead of the Road version in Ares.
export const inputs: string[] = ["/planning/seed", "/simulation/pose"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/scenario_dnn/sim_drivable_space";

export const config: ScriptConfig = {};

const NUM_CANDIDATES = 10;
const GEOMETRIC_POINTS = 80;
const TRAJECTORY_POINTS = 80;
const TENSOR_TO_METERS = 10.0;
// Gen4 (GAC_A2T) production car model: wheel_base = 2.75 m.
const GEN4_WHEEL_BASE_METERS = 2.75;

const publisher = (
  messages: Record<string, Input<"/planning/seed"> | Input<"/pose">>,
  _globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  // /simulation/pose has the same payload shape as /pose, but is absent from
  // the Road type map, so it must not be used as Input<...> generic.
  const poseInput = messages["/simulation/pose"] as unknown as Input<"/pose">;
  if (poseInput == null) {
    return undefined;
  }

  const seed = messages["/planning/seed"] as Input<"/planning/seed">;
  if (seed == null) {
    return undefined;
  }

  const { receiveTime } = seed;
  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),
  ];

  const modelOutput =
    seed.message.behaviorSeed.assistStuckSeed.assistStuckModelOutput;
  if (modelOutput == null) {
    return { markers };
  }

  const tensorDict = modelOutput.tensorDict as unknown as Record<
    string,
    Messages.planner__pb__RATensor
  >;
  const coordinateOrigin =
    tensorDict["assist_stuck_coordinate_origin"]?.floatVals;

  // Do not gate rendering on previousTimestamp: its clock can differ from the
  // localization clock in road-test bags. This intentionally matches the
  // original scripts current-pose rendering behavior.
  // /simulation/pose is the centre of the wheelbase.  The feature extractor
  // instead uses RobotStateSnapshot::{x,y}, which are the rear-axle centre.
  // Convert to that exact tensor origin before applying the inverse transform.
  const poseYaw = poseInput.message.yaw;
  const rearAxleOffset = GEN4_WHEEL_BASE_METERS / 2;
  const alignedPose =
    coordinateOrigin != null && coordinateOrigin.length >= 3
      ? {
          x: coordinateOrigin[0],
          y: coordinateOrigin[1],
          z: poseInput.message.z,
          yaw: coordinateOrigin[2],
        }
      : {
          x: poseInput.message.x - rearAxleOffset * Math.cos(poseYaw),
          y: poseInput.message.y - rearAxleOffset * Math.sin(poseYaw),
          z: poseInput.message.z,
          yaw: poseYaw,
        };

  const geometric = tensorDict["drivable_space_geometric"]?.floatVals;
  const validGeometric = tensorDict["drivable_space_valid_geometric"]?.intVals;
  const trajectory = tensorDict["drivable_space_trajectory"]?.floatVals;
  const validTrajectory =
    tensorDict["drivable_space_valid_trajectory"]?.intVals;
  const selected = tensorDict["drivable_space_discrete"]?.intVals;

  if (geometric == null || validGeometric == null) {
    return { markers };
  }

  const cosYaw = Math.cos(alignedPose.yaw);
  const sinYaw = Math.sin(alignedPose.yaw);
  const polygonZ = alignedPose.z - 0.8;

  // Inverse of ConstructTensors():
  // local = 0.1 * R(-ego_yaw) * (world - ego_position).
  const toWorld = (localX: number, localY: number) => ({
    x:
      localX * TENSOR_TO_METERS * cosYaw -
      localY * TENSOR_TO_METERS * sinYaw +
      alignedPose.x,
    y:
      localX * TENSOR_TO_METERS * sinYaw +
      localY * TENSOR_TO_METERS * cosYaw +
      alignedPose.y,
  });

  for (let candidate = 0; candidate < NUM_CANDIDATES; ++candidate) {
    const isSelected = selected?.[candidate] === 1;
    // Sim view: draw only the trajectory selected by Planning.
    if (!isSelected) {
      continue;
    }
    const polygonColor = isSelected
      ? { r: 0.1, g: 1.0, b: 0.25, a: 1.0 } // selected: green
      : { r: 0.2, g: 0.8, b: 1.0, a: 1.0 }; // unselected: light blue
    const pathColor = isSelected
      ? { r: 0.55, g: 1.0, b: 0.65, a: 1.0 }
      : { r: 0.35, g: 0.85, b: 1.0, a: 1.0 };

    // geometric shape: [1, 10, 1, 81, 2].  The 81st point is a duplicated
    // first point for closure; validGeometric itself is capped at 80.
    const polygonCount = Math.min(
      validGeometric[candidate] ?? 0,
      GEOMETRIC_POINTS,
    );
    const polygonBase = candidate * (GEOMETRIC_POINTS + 1) * 2;
    const polygonPoints: { x: number; y: number; z: number }[] = [];

    for (let point = 0; point < polygonCount; ++point) {
      const offset = polygonBase + point * 2;
      const world = toWorld(geometric[offset], geometric[offset + 1]);
      polygonPoints.push({ ...world, z: polygonZ });
    }

    if (polygonPoints.length >= 3) {
      markers.push({
        header: { frame_id: "world", stamp: receiveTime, seq: 0 },
        id: `drivable_space_polygon_${candidate}`,
        type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
        action: 0,
        points: polygonPoints,
        color: polygonColor,
        lineMetadata: {
          lineWidth: isSelected ? 0.45 : 0.25,
          closed: true,
        },
      });
    }

    // trajectory shape: [1, 10, 1, 80, 4], with each point laid out as
    // [x, y, heading, speed].  Only x/y are meaningful in this CR.
    const trajectoryCount = Math.min(
      validTrajectory?.[candidate] ?? 0,
      TRAJECTORY_POINTS,
    );
    const trajectoryBase = candidate * TRAJECTORY_POINTS * 4;
    const trajectoryPoints: { x: number; y: number; z: number }[] = [];

    if (trajectory != null) {
      for (let point = 0; point < trajectoryCount; ++point) {
        const offset = trajectoryBase + point * 4;
        const world = toWorld(trajectory[offset], trajectory[offset + 1]);
        trajectoryPoints.push({
          ...world,
          // Keep the reference line above the map and polygon.
          z: alignedPose.z + 0.5,
        });
      }
    }

    if (trajectoryPoints.length >= 2) {
      markers.push({
        header: { frame_id: "world", stamp: receiveTime, seq: 0 },
        id: `drivable_space_reference_path_${candidate}`,
        type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
        action: 0,
        points: trajectoryPoints,
        color: pathColor,
        lineMetadata: {
          lineWidth: isSelected ? 1.0 : 0.25,
          closed: false,
        },
      });
    }
  }

  return { markers };
};

export default publisher;
