import { Input, Messages } from "ros";
import {
  GlobalVariables,
  ScriptConfig,
  createDeleteCurrentTopicMarkers,
  getObjectId,
  getIntentionPlanDebug,
  getSpeedSolverDebugIndex,
} from "@ares-utils";

export const inputs: string[] = [
  "/planning/planning_debug",
  "/pose",
  "/perception/tracked_object_list",
];

export const output: `/${"studio_node" | "image_marker"}/${string}` =
  "/studio_node/assist/vlm/dominant_constraint";

export const config: ScriptConfig = {
  executeScriptWhenAnyMessageReceived: true,
};

// Dominant is a planning-state overlay, not another object class. Keep the
// object's original class color visible and indicate dominant state with an
// opaque lavender outline only.
const OUTLINE_COLOR = { r: 0.86, g: 0.48, b: 1.0, a: 1.0 };
const FILL_HEIGHT_M = 3.5;
const Z_OFFSET_M = 0.2;
const OUTLINE_WIDTH_M = 0.35;
const RENDER_ORDER = 2000;
// Keep the diagnostic/DOM text implementation available for debugging, but do
// not put persistent text boxes into BEV captures.
const SHOW_SCREEN_TEXT = false;

type PlanningInput = Input<"/planning/planning_debug">;
type PoseInput = Input<"/pose">;
type TrackedInput = Input<"/perception/tracked_object_list">;
type ReasoningObject = Messages.planner__speed__pb__ReasoningObjectDebug;

type DrawableObject = {
  objectId: number | string;
  contour: Messages.voy__Point2d[];
};

type ResolvedDominantObject = {
  object: DrawableObject;
  source: string;
};

let latestPlanningInput: PlanningInput | undefined;
let latestPoseInput: PoseInput | undefined;
let latestTrackedInput: TrackedInput | undefined;

const findContourObject = (
  reasoningObjects: ReasoningObject[],
  objectId: number | string | undefined,
): ReasoningObject | undefined => {
  if (objectId == undefined) {
    return undefined;
  }

  return reasoningObjects.find(
    (object) =>
      String(object.objectId) === String(objectId) &&
      (object.contour?.length ?? 0) >= 3,
  );
};

const findTrackedContourObject = (
  trackedObjects: Messages.voy__TrackedObject[],
  objectId: number | string | undefined,
): DrawableObject | undefined => {
  if (objectId == undefined) {
    return undefined;
  }

  const trackedObject = trackedObjects.find(
    (object) => String(object.id) === String(objectId),
  );
  if (trackedObject == undefined) {
    return undefined;
  }

  if ((trackedObject.contour?.length ?? 0) >= 3) {
    return {
      objectId: trackedObject.id,
      contour: trackedObject.contour,
    };
  }

  // Some bags omit tracked-object contours. Reconstruct the physical 2D box
  // from center/dimensions/heading instead of silently dropping the object.
  if (
    !Number.isFinite(trackedObject.centerX) ||
    !Number.isFinite(trackedObject.centerY) ||
    !Number.isFinite(trackedObject.length) ||
    !Number.isFinite(trackedObject.width) ||
    !Number.isFinite(trackedObject.heading) ||
    trackedObject.length <= 0 ||
    trackedObject.width <= 0
  ) {
    return undefined;
  }

  const halfLength = trackedObject.length / 2;
  const halfWidth = trackedObject.width / 2;
  const cosHeading = Math.cos(trackedObject.heading);
  const sinHeading = Math.sin(trackedObject.heading);
  const localCorners: Array<[number, number]> = [
    [halfLength, halfWidth],
    [halfLength, -halfWidth],
    [-halfLength, -halfWidth],
    [-halfLength, halfWidth],
  ];
  const contour = localCorners.map(([localX, localY]) => ({
    x:
      trackedObject.centerX +
      localX * cosHeading -
      localY * sinHeading,
    y:
      trackedObject.centerY +
      localX * sinHeading +
      localY * cosHeading,
  }));

  return {
    objectId: trackedObject.id,
    contour,
  };
};

const createDiagnosticText = (
  receiveTime: Messages.ares__Time,
  pose: { x: number; y: number; z: number },
  text: string,
): Messages.ares__VisualizationMarker => ({
  header: { frame_id: "world", stamp: receiveTime, seq: 0 },
  ns: "dominant_constraint_diagnostic",
  id: "dominant_constraint_diagnostic",
  type: Messages.ares__VisualizationMarkerTypes.TEXT,
  action: 0,
  pose: {
    position: { x: pose.x, y: pose.y, z: pose.z + 4.5 },
    orientation: { x: 0, y: 0, z: 0, w: 1 },
  },
  scale: { x: 1, y: 1, z: 1 },
  color: { r: 1, g: 1, b: 1, a: 1 },
  renderOrder: RENDER_ORDER + 3,
  textMetadata: {
    convertType: Messages.ares__TextConvertType.TEXT,
    text,
    textStyle: {
      textAlign: "center",
      fontSize: "14px",
      background: "rgba(0, 0, 0, 0.78)",
      padding: "3px 6px",
    },
  },
});

const resolveDominantObject = (
  searchDebug: Messages.planner__speed__pb__SpeedSearchDebug,
  speedGeneratorDebug: Messages.planner__speed__pb__SpeedGeneratorDebug,
  trackedObjects: Messages.voy__TrackedObject[],
): ResolvedDominantObject | undefined => {
  const reasoningObjects =
    speedGeneratorDebug.speedReasoningDebug?.inputDebug?.reasoningObjects ?? [];
  const index = searchDebug.dominantConstraintIx;
  const validIndex = Number.isInteger(index) && index >= 0;

  const searchConstraint = validIndex
    ? searchDebug.constraints?.[index]
    : undefined;
  const primitiveConstraint = validIndex
    ? speedGeneratorDebug.primitiveConstraints?.[index]
    : undefined;
  const candidates: Array<{
    objectId: number | string | undefined;
    source: string;
  }> = [
    {
      objectId: searchDebug.dominantConstraintObjId,
      source: "dominantConstraintObjId",
    },
    {
      objectId: validIndex
        ? searchConstraint?.objId
        : undefined,
      source: "searchDebug.constraints",
    },
    {
      objectId: validIndex
        ? primitiveConstraint?.objId
        : undefined,
      source: "primitiveConstraints",
    },
    {
      objectId: getObjectId(searchConstraint?.uniqueConstraintId),
      source: "searchDebug.uniqueConstraintId",
    },
    {
      objectId: getObjectId(primitiveConstraint?.uniqueConstraintId),
      source: "primitiveConstraints.uniqueConstraintId",
    },
  ];

  for (const candidate of candidates) {
    const object = findContourObject(reasoningObjects, candidate.objectId);
    if (object != undefined) {
      return { object, source: `${candidate.source}+reasoningObjects` };
    }

    const trackedObject = findTrackedContourObject(
      trackedObjects,
      candidate.objectId,
    );
    if (trackedObject != undefined) {
      return {
        object: trackedObject,
        source: `${candidate.source}+tracked_object_list`,
      };
    }
  }

  return undefined;
};

const flattenContour = (
  contour: Messages.voy__Point2d[],
): Float32Array => {
  const points = new Float32Array(contour.length * 3);
  contour.forEach((point, index) => {
    points[index * 3] = point.x;
    points[index * 3 + 1] = point.y;
    points[index * 3 + 2] = 0.0;
  });
  return points;
};

const contourCenter = (contour: Messages.voy__Point2d[]) => {
  const sum = contour.reduce(
    (center, point) => ({
      x: center.x + point.x,
      y: center.y + point.y,
    }),
    { x: 0, y: 0 },
  );

  return {
    x: sum.x / contour.length,
    y: sum.y / contour.length,
  };
};

const publisher = (
  messages: Record<string, PlanningInput | PoseInput | TrackedInput>,
  globalVars: GlobalVariables,
): Messages.ares__VisualizationMarkerArray | undefined => {
  const planningInput = messages["/planning/planning_debug"] as
    | PlanningInput
    | undefined;
  const poseInput = messages["/pose"] as PoseInput | undefined;
  const trackedInput = messages["/perception/tracked_object_list"] as
    | TrackedInput
    | undefined;

  if (planningInput != undefined) {
    latestPlanningInput = planningInput;
  }
  if (poseInput != undefined) {
    latestPoseInput = poseInput;
  }
  if (trackedInput != undefined) {
    latestTrackedInput = trackedInput;
  }

  const currentPlanningInput = latestPlanningInput;
  const currentPose =
    currentPlanningInput?.message.pose ?? latestPoseInput?.message;

  if (currentPlanningInput == undefined) {
    return undefined;
  }

  const markers: Messages.ares__VisualizationMarker[] = [
    createDeleteCurrentTopicMarkers(currentPlanningInput.receiveTime),
  ];

  if (currentPose == undefined) {
    return { markers };
  }

  const behaviorReasonerDebug =
    currentPlanningInput.message.behaviorReasonerDebug;
  const intentionPlanDebug = getIntentionPlanDebug(
    behaviorReasonerDebug,
    globalVars,
  );
  const speedGeneratorDebug = intentionPlanDebug?.speedGeneratorDebug as
    | Messages.planner__speed__pb__SpeedGeneratorDebug
    | undefined;

  if (speedGeneratorDebug == undefined) {
    if (SHOW_SCREEN_TEXT) {
      markers.push(
        createDiagnosticText(
          currentPlanningInput.receiveTime,
          currentPose,
          "DOM: no speedGeneratorDebug",
        ),
      );
    }
    return { markers };
  }

  const solverIndex = getSpeedSolverDebugIndex(
    behaviorReasonerDebug,
    globalVars,
  );
  const searchDebug =
    speedGeneratorDebug.speedSolverDebugs?.[solverIndex]?.searchDebug;

  if (searchDebug == undefined) {
    if (SHOW_SCREEN_TEXT) {
      markers.push(
        createDiagnosticText(
          currentPlanningInput.receiveTime,
          currentPose,
          `DOM: no searchDebug (solver=${solverIndex})`,
        ),
      );
    }
    return { markers };
  }

  const trackedObjects = latestTrackedInput?.message.trackedObjects ?? [];
  const resolved = resolveDominantObject(
    searchDebug,
    speedGeneratorDebug,
    trackedObjects,
  );
  if (resolved == undefined) {
    const index = searchDebug.dominantConstraintIx;
    const searchObjectId =
      Number.isInteger(index) && index >= 0
        ? searchDebug.constraints?.[index]?.objId
        : undefined;
    const primitiveObjectId =
      Number.isInteger(index) && index >= 0
        ? speedGeneratorDebug.primitiveConstraints?.[index]?.objId
        : undefined;
    const reasoningObjects =
      speedGeneratorDebug.speedReasoningDebug?.inputDebug?.reasoningObjects ?? [];
    const searchConstraintId =
      Number.isInteger(index) && index >= 0
        ? searchDebug.constraints?.[index]?.uniqueConstraintId
        : undefined;
    const primitiveConstraintId =
      Number.isInteger(index) && index >= 0
        ? speedGeneratorDebug.primitiveConstraints?.[index]
            ?.uniqueConstraintId
        : undefined;
    const contourObjectIds = reasoningObjects
      .filter((object) => (object.contour?.length ?? 0) >= 3)
      .slice(0, 8)
      .map((object) => String(object.objectId))
      .join(",");

    if (SHOW_SCREEN_TEXT) {
      markers.push(
        createDiagnosticText(
          currentPlanningInput.receiveTime,
          currentPose,
          `DOM unresolved\nix=${index} direct=${String(
            searchDebug.dominantConstraintObjId,
          )}\nsearch=${String(searchObjectId)} primitive=${String(
            primitiveObjectId,
          )}\nsearchId=${String(searchConstraintId)}\nprimitiveId=${String(
            primitiveConstraintId,
          )}\nreasoning=${reasoningObjects.length} contourIds=[${
            contourObjectIds
          }] tracked=${trackedObjects.length}`,
        ),
      );
    }
    return { markers };
  }

  const { object, source } = resolved;
  const contour = object.contour;
  const center = contourCenter(contour);
  const markerZ = currentPose.z + Z_OFFSET_M;
  const topZ = markerZ + FILL_HEIGHT_M + 0.05;
  const outlinePoints = contour.map((point) => ({
    x: point.x,
    y: point.y,
    z: topZ,
  }));

  // Explicitly close the outline; this also works on Ares builds where the
  // LINE_STRIP "closed" metadata is not honored consistently.
  outlinePoints.push({ ...outlinePoints[0]! });

  markers.push(
    {
      header: {
        frame_id: "world",
        stamp: currentPlanningInput.receiveTime,
        seq: 0,
      },
      ns: "dominant_constraint_extruded_outline",
      id: `dominant_constraint_extruded_outline_${object.objectId}`,
      type: Messages.ares__VisualizationMarkerTypes.SHAPE_EXTRUDE,
      action: 0,
      pose: {
        position: { x: 0, y: 0, z: markerZ },
        orientation: { x: 0, y: 0, z: 0, w: 1 },
      },
      scale: { x: 1, y: 1, z: 1 },
      flattenedPoints: flattenContour(contour),
      color: OUTLINE_COLOR,
      fill: false,
      edge: true,
      edgeColor: OUTLINE_COLOR,
      edgeWidth: OUTLINE_WIDTH_M,
      renderOrder: RENDER_ORDER,
      shapeMetadata: { height: FILL_HEIGHT_M },
      displayHoverBubble: true,
      bubbleTextOnHover:
        `Dominant Constraint\nobject_id=${object.objectId}\nsource=${source}`,
    },
  );

  markers.push({
    header: {
      frame_id: "world",
      stamp: currentPlanningInput.receiveTime,
      seq: 0,
    },
    ns: "dominant_constraint_outline",
    id: `dominant_constraint_outline_${object.objectId}`,
    type: Messages.ares__VisualizationMarkerTypes.LINE_STRIP,
    action: 0,
    points: outlinePoints,
    color: OUTLINE_COLOR,
    renderOrder: RENDER_ORDER + 1,
    lineMetadata: {
      lineWidth: OUTLINE_WIDTH_M,
      closed: false,
    },
  });

  if (SHOW_SCREEN_TEXT) {
    markers.push({
      header: {
        frame_id: "world",
        stamp: currentPlanningInput.receiveTime,
        seq: 0,
      },
      ns: "dominant_constraint_text",
      id: `dominant_constraint_text_${object.objectId}`,
      type: Messages.ares__VisualizationMarkerTypes.TEXT,
      action: 0,
      pose: {
        position: {
          x: center.x,
          y: center.y,
          z: topZ + 0.6,
        },
        orientation: { x: 0, y: 0, z: 0, w: 1 },
      },
      scale: { x: 1, y: 1, z: 1 },
      color: OUTLINE_COLOR,
      renderOrder: RENDER_ORDER + 2,
      textMetadata: {
        convertType: Messages.ares__TextConvertType.TEXT,
        text: `DOM ${object.objectId}\n${source}`,
        textStyle: {
          textAlign: "center",
          fontSize: "16px",
          background: "rgba(0, 0, 0, 0.68)",
          padding: "3px 6px",
        },
      },
    });
  }

  return { markers };
};

export default publisher;
