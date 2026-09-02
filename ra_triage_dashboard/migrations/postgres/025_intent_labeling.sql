-- Independent Routing / ego-lane-change annotation snapshots.

BEGIN;

CREATE TABLE IF NOT EXISTS intent_label_revisions (
    id bigserial PRIMARY KEY,
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    routing_default varchar(32)
        CHECK(routing_default IS NULL OR routing_default IN (
            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
        )),
    lane_change_default varchar(32)
        CHECK(lane_change_default IS NULL OR lane_change_default IN (
            'lane_change', 'no_lane_change'
        )),
    author varchar(128) NOT NULL DEFAULT '',
    author_source varchar(64) NOT NULL DEFAULT 'legacy',
    author_verified boolean NOT NULL DEFAULT false,
    supersedes_id bigint REFERENCES intent_label_revisions(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_label_revisions_case
    ON intent_label_revisions(dataset_id, case_id, id DESC);

CREATE TABLE IF NOT EXISTS intent_frame_overrides (
    revision_id bigint NOT NULL REFERENCES intent_label_revisions(id) ON DELETE CASCADE,
    timepoint_id varchar(96) NOT NULL,
    offset_ms integer NOT NULL,
    routing_intent varchar(32)
        CHECK(routing_intent IS NULL OR routing_intent IN (
            'left_turn', 'right_turn', 'straight', 'u_turn', 'parking'
        )),
    lane_change_intent varchar(32)
        CHECK(lane_change_intent IS NULL OR lane_change_intent IN (
            'lane_change', 'no_lane_change'
        )),
    PRIMARY KEY (revision_id, timepoint_id),
    CHECK(routing_intent IS NOT NULL OR lane_change_intent IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_intent_frame_overrides_offset
    ON intent_frame_overrides(revision_id, offset_ms ASC);

CREATE TABLE IF NOT EXISTS intent_label_heads (
    dataset_id varchar(128) NOT NULL,
    case_id varchar(160) NOT NULL,
    current_revision_id bigint NOT NULL REFERENCES intent_label_revisions(id),
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, case_id)
);

DO $$
DECLARE
    table_name text;
    operation text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'intent_label_revisions',
        'intent_frame_overrides',
        'intent_label_heads'
    ]
    LOOP
        FOREACH operation IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE']
        LOOP
            EXECUTE format(
                'DROP TRIGGER IF EXISTS %I ON %I',
                'trg_' || table_name || '_' || lower(operation) || '_change_revision',
                table_name
            );
            EXECUTE format(
                'CREATE TRIGGER %I AFTER %s ON %I FOR EACH STATEMENT '
                'EXECUTE FUNCTION bump_dashboard_change_revision()',
                'trg_' || table_name || '_' || lower(operation) || '_change_revision',
                operation,
                table_name
            );
        END LOOP;
    END LOOP;
END;
$$;

COMMIT;
