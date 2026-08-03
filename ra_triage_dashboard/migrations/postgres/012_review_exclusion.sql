-- Persist the human decision that an Issue is outside the model's scope.
-- This is a Review-version field, so older annotations remain unchanged.

BEGIN;

ALTER TABLE annotations
    ADD COLUMN IF NOT EXISTS is_excluded boolean NOT NULL DEFAULT false;

COMMIT;
