-- Expand intent lane-change labels from binary to no/left/right while keeping
-- the legacy `lane_change` value readable for historical annotations.

BEGIN;

ALTER TABLE intent_label_revisions
    DROP CONSTRAINT IF EXISTS intent_label_revisions_lane_change_default_check;

ALTER TABLE intent_label_revisions
    ADD CONSTRAINT intent_label_revisions_lane_change_default_check
    CHECK (lane_change_default IS NULL OR lane_change_default IN (
        'lane_change', 'no_lane_change', 'left_lane_change', 'right_lane_change'
    ));

ALTER TABLE intent_frame_overrides
    DROP CONSTRAINT IF EXISTS intent_frame_overrides_lane_change_intent_check;

ALTER TABLE intent_frame_overrides
    ADD CONSTRAINT intent_frame_overrides_lane_change_intent_check
    CHECK (lane_change_intent IS NULL OR lane_change_intent IN (
        'lane_change', 'no_lane_change', 'left_lane_change', 'right_lane_change'
    ));

COMMIT;
