-- Bind Review versions to the immutable Model Run they describe.  Existing
-- records remain readable as legacy unbound Reviews (empty model_run_id).

BEGIN;

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS model_run_id varchar(36) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_annotations_issue_run_created
    ON annotations(issue_id, model_run_id, id DESC);

COMMIT;
