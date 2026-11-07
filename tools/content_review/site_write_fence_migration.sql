CREATE TABLE `content_review_write_fence` (
	`fence_id` text PRIMARY KEY NOT NULL,
	`operation_id` text NOT NULL,
	`owner` text NOT NULL,
	`run_id` text NOT NULL,
	`expected_head` text NOT NULL,
	`expected_tree` text NOT NULL,
	`receipt_path` text NOT NULL,
	`receipt_blob_sha` text NOT NULL,
	`phase` text NOT NULL,
	`acquired_at` text NOT NULL,
	CONSTRAINT "content_review_fence_singleton" CHECK("content_review_write_fence"."fence_id" = 'content-review'),
	CONSTRAINT "content_review_fence_head_length" CHECK(length("content_review_write_fence"."expected_head") = 40),
	CONSTRAINT "content_review_fence_tree_length" CHECK(length("content_review_write_fence"."expected_tree") = 40),
	CONSTRAINT "content_review_fence_receipt_length" CHECK(length("content_review_write_fence"."receipt_blob_sha") = 40),
	CONSTRAINT "content_review_fence_phase" CHECK("content_review_write_fence"."phase" IN ('preparing', 'committing'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `content_review_write_fence_operation_id_unique` ON `content_review_write_fence` (`operation_id`);
--> statement-breakpoint
CREATE TRIGGER content_review_fence_submissions_insert
BEFORE INSERT ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_submissions_update
BEFORE UPDATE ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_submissions_delete
BEFORE DELETE ON review_submissions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_decisions_insert
BEFORE INSERT ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_decisions_update
BEFORE UPDATE ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_decisions_delete
BEFORE DELETE ON review_decisions WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_jobs_insert
BEFORE INSERT ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_jobs_update
BEFORE UPDATE ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
--> statement-breakpoint
CREATE TRIGGER content_review_fence_jobs_delete
BEFORE DELETE ON review_jobs WHEN EXISTS (SELECT 1 FROM content_review_write_fence)
BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END;
