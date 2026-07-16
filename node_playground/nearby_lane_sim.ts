import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
} from "@ares-utils";

// Simulation-only version. Load this instead of the Road version in Ares.
export const inputs: string[] = ["/planning/seed", "/simulation/pose"];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/scenario_dnn/sim_nearby_lane";

export const config: ScriptConfig = {};

// Used to overlap region upon other shapes.
const z_buffer = 0.1;
// Gen4 (GAC_A2T) production car model: wheel_base = 2.75 m.
const GEN4_WHEEL_BASE_METERS = 2.75;

const publisher = (
  messages: Record<string, Input<"/planning/seed"> | Input<"/pose">>,
  globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const message_debug = messages["/planning/seed"] as Input<"/planning/seed">;
  // /simulation/pose has the same payload shape as /pose.
  const message_pose = messages[
    "/simulation/pose"
  ] as unknown as Input<"/pose">;
  if (!message_debug || !message_pose) {
    return undefined;
  }

  const tensorDict = message_debug.message.behaviorSeed.assistStuckSeed
    .assistStuckModelOutput.tensorDict as unknown as Record<
    string,
    Messages.planner__pb__RATensor
  >;

  if (tensorDict == null) {
    return undefined;
  }
  const pose_z = message_pose.message.z + z_buffer;

  const {
    receiveTime,
    message: {},
  } = message_debug;

  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(receiveTime),
  ];

  if (
    !tensorDict["nearby_lane_geometric"] ||
    !tensorDict["nearby_lane_valid_geometric"]
  ) {
    return undefined;
  }
  const lane_geometric = tensorDict["nearby_lane_geometric"].floatVals;
  const coordinateOrigin =
    tensorDict["assist_stuck_coordinate_origin"]?.floatVals;
  const lane_valid_geometric =
    tensorDict["nearby_lane_valid_geometric"].intVals;
  const poseYaw = message_pose.message.yaw;
  const rearAxleOffset = GEN4_WHEEL_BASE_METERS / 2;
  // Prefer the exact frame that generated the tensors.  Older bags do not
  // have it, so keep the Gen4 wheelbase-centre to rear-axle fallback.
  const [coordinate_x, coordinate_y, coordinate_yaw] =
    coordinateOrigin != null && coordinateOrigin.length >= 3
      ? [coordinateOrigin[0], coordinateOrigin[1], coordinateOrigin[2]]
      : [
          message_pose.message.x - rearAxleOffset * Math.cos(poseYaw),
          message_pose.message.y - rearAxleOffset * Math.sin(poseYaw),
          poseYaw,
        ];
  if (!lane_geometric || !lane_valid_geometric) {
    return undefined;
  }

  const lane_num = 90;
  const points_per_lane = 62;
  const pose_scaling = 10.0;
  for (let lane_idx = 0; lane_idx < lane_num; lane_idx++) {
    const valid_point_count = lane_valid_geometric[lane_idx];
    if (valid_point_count <= 0) continue;

    const lane_start_index = lane_idx * points_per_lane * 2;
    const points = [];
    const cosYaw = Math.cos(coordinate_yaw);
    const sinYaw = Math.sin(coordinate_yaw);

    for (let point_idx = 0; point_idx < valid_point_count; point_idx++) {
      const point_start_index = lane_start_index + point_idx * 2;
      const local_x = lane_geometric[point_start_index] * pose_scaling;
      const local_y = lane_geometric[point_start_index + 1] * pose_scaling;

      const rotated_x = local_x * cosYaw - local_y * sinYaw;
      const rotated_y = local_x * sinYaw + local_y * cosYaw;
      const world_x = rotated_x + coordinate_x;
      const world_y = rotated_y + coordinate_y;

      points.push({
        x: world_x,
        y: world_y,
        z: pose_z - z_buffer - 1.0,
      });
    }

    const lane_marker = {
      header: {
        frame_id: "world",
        stamp: receiveTime,
        seq: 0,
      },
      id: "lane_polygon_" + lane_idx,
      type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
      action: 0,
      points,
      color: {
        r: 0.0,
        g: 0.4,
        b: 0.5,
        a: 1.0,
      },
      lineMetadata: {
        lineWidth: 0.5,
        closed: true,
      },
    };

    markers.push(lane_marker);
  }

  return { markers };
};

export default publisher;
