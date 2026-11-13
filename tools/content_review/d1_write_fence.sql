-- Additive schema for a single non-expiring review checkpoint fence. An
-- ambiguous GitHub outcome must be reconciled before its row is deleted.
CREATE TABLE IF NOT EXISTS content_review_write_fence (
  fence_id TEXT PRIMARY KEY CHECK (fence_id = 'content-review'),
  operation_id TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL,
  run_id TEXT NOT NULL,
  expected_head TEXT NOT NULL CHECK (length(expected_head) = 40),
  expected_tree TEXT NOT NULL CHECK (length(expected_tree) = 40),
  receipt_path TEXT NOT NULL,
  receipt_blob_sha TEXT NOT NULL CHECK (length(receipt_blob_sha) = 40),
  phase TEXT NOT NULL CHECK (phase IN ('preparing', 'committing')),
  acquired_at TEXT NOT NULL
);

-- All submission, decision and review-job writers share this database fence.
-- Triggers execute inside the same SQLite transaction as the attempted write.
CREATE TRIGGER IF NOT EXISTS content_review_fence_submissions_insert
BEFORE INSERT ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_submissions_update
BEFORE UPDATE ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_submissions_delete
BEFORE DELETE ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_decisions_insert
BEFORE INSERT ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_decisions_update
BEFORE UPDATE ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_decisions_delete
BEFORE DELETE ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_jobs_insert
BEFORE INSERT ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_jobs_update
BEFORE UPDATE ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
CREATE TRIGGER IF NOT EXISTS content_review_fence_jobs_delete
BEFORE DELETE ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
