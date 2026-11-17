CREATE TABLE `aliases` (
	`identity` text PRIMARY KEY NOT NULL,
	`candidate_id` text NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `attempt_events` (
	`id` integer PRIMARY KEY NOT NULL,
	`job_id` integer NOT NULL,
	`lease` text NOT NULL,
	`event` text NOT NULL,
	`at` real NOT NULL,
	`detail` text NOT NULL,
	FOREIGN KEY (`job_id`) REFERENCES `jobs`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `candidates` (
	`id` text PRIMARY KEY NOT NULL,
	`identity` text NOT NULL,
	`payload` text NOT NULL,
	`content_hash` text NOT NULL,
	`state` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `candidates_identity_unique` ON `candidates` (`identity`);--> statement-breakpoint
CREATE TABLE `checks` (
	`candidate_id` text NOT NULL,
	`content_hash` text NOT NULL,
	`name` text NOT NULL,
	`result` text NOT NULL,
	`evidence` text NOT NULL,
	PRIMARY KEY(`candidate_id`, `content_hash`, `name`),
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `runtime_control` (
	`id` integer PRIMARY KEY NOT NULL,
	`policy_hash` text NOT NULL,
	`implementation_hash` text NOT NULL,
	`phase` text NOT NULL,
	`ticks` integer NOT NULL,
	`max_ticks` integer NOT NULL,
	`deadline` real NOT NULL,
	`active_token` text,
	`active_until` real,
	`interrupted_lease` text,
	`interrupted_job` integer,
	`replays_verified` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE `decisions` (
	`id` text PRIMARY KEY NOT NULL,
	`candidate_id` text NOT NULL,
	`content_hash` text NOT NULL,
	`verdict` text NOT NULL,
	`actor` text NOT NULL,
	`reason` text NOT NULL,
	`at` real NOT NULL,
	`origin` text NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `decisions_candidate_id_unique` ON `decisions` (`candidate_id`);--> statement-breakpoint
CREATE TABLE `discoveries` (
	`source` text NOT NULL,
	`receipt` text NOT NULL,
	`payload_hash` text NOT NULL,
	`candidate_id` text NOT NULL,
	PRIMARY KEY(`source`, `receipt`),
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `retained_documents` (
	`candidate_id` text PRIMARY KEY NOT NULL,
	`content_hash` text NOT NULL,
	`receipt` text NOT NULL,
	`receipt_hash` text NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `external_effect_events` (
	`id` integer PRIMARY KEY NOT NULL,
	`request_hash` text NOT NULL,
	`event` text NOT NULL,
	`receipt` text NOT NULL,
	`at` real NOT NULL,
	FOREIGN KEY (`request_hash`) REFERENCES `external_effects`(`request_hash`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `external_effects` (
	`request_hash` text PRIMARY KEY NOT NULL,
	`request` text NOT NULL,
	`state` text NOT NULL,
	`token` text,
	`attempts` integer DEFAULT 0 NOT NULL,
	`response` text,
	`response_hash` text,
	`not_before` real DEFAULT 0 NOT NULL,
	`reason` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `intake_holds` (
	`receipt_hash` text PRIMARY KEY NOT NULL,
	`source` text NOT NULL,
	`record` text NOT NULL,
	`reason` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `jobs` (
	`id` integer PRIMARY KEY NOT NULL,
	`candidate_id` text NOT NULL,
	`stage` text NOT NULL,
	`status` text NOT NULL,
	`lease` text,
	`lease_until` real,
	`attempts` integer DEFAULT 0 NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `candidate_stage` ON `jobs` (`candidate_id`,`stage`);--> statement-breakpoint
CREATE TABLE `source_outcomes` (
	`receipt_hash` text PRIMARY KEY NOT NULL,
	`source` text NOT NULL,
	`status` text NOT NULL,
	`discovered` integer NOT NULL,
	`held` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `preview_current` (
	`id` integer PRIMARY KEY NOT NULL,
	`generation` text NOT NULL,
	FOREIGN KEY (`generation`) REFERENCES `preview_generations`(`generation`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `preview_files` (
	`generation` text NOT NULL,
	`name` text NOT NULL,
	`body` text NOT NULL,
	`body_hash` text NOT NULL,
	PRIMARY KEY(`generation`, `name`)
);
--> statement-breakpoint
CREATE TABLE `preview_generations` (
	`generation` text PRIMARY KEY NOT NULL,
	`manifest` text NOT NULL,
	`created_at` real NOT NULL
);
--> statement-breakpoint
CREATE TABLE `publications` (
	`candidate_id` text PRIMARY KEY NOT NULL,
	`decision_id` text NOT NULL,
	`content_hash` text NOT NULL,
	`record` text NOT NULL,
	`at` real NOT NULL,
	FOREIGN KEY (`candidate_id`) REFERENCES `candidates`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`decision_id`) REFERENCES `decisions`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `publications_decision_id_unique` ON `publications` (`decision_id`);--> statement-breakpoint
CREATE TABLE `worker_receipts` (
	`id` text PRIMARY KEY NOT NULL,
	`scheduled_time` integer NOT NULL,
	`cron` text NOT NULL,
	`implementation_hash` text NOT NULL,
	`status` text NOT NULL,
	`completed_jobs` integer NOT NULL,
	`detail` text NOT NULL
);

--> statement-breakpoint
CREATE TRIGGER publication_gate BEFORE INSERT ON publications WHEN NOT EXISTS (SELECT 1 FROM decisions d JOIN candidates c ON c.id=d.candidate_id WHERE d.id=NEW.decision_id AND d.candidate_id=NEW.candidate_id AND d.verdict='approve' AND d.content_hash=NEW.content_hash AND c.content_hash=NEW.content_hash AND c.state='approved' AND (SELECT count(*) FROM checks k WHERE k.candidate_id=c.id AND k.content_hash=c.content_hash AND k.result='pass' AND k.name IN ('metadata','access','format','relevance','quality'))=5) BEGIN SELECT RAISE(ABORT,'publication_gate'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_attempt_events_UPDATE BEFORE UPDATE ON attempt_events BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_attempt_events_DELETE BEFORE DELETE ON attempt_events BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_checks_UPDATE BEFORE UPDATE ON checks BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_checks_DELETE BEFORE DELETE ON checks BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_decisions_UPDATE BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_decisions_DELETE BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_publications_UPDATE BEFORE UPDATE ON publications BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_publications_DELETE BEFORE DELETE ON publications BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_discoveries_UPDATE BEFORE UPDATE ON discoveries BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_discoveries_DELETE BEFORE DELETE ON discoveries BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_retained_documents_UPDATE BEFORE UPDATE ON retained_documents BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_retained_documents_DELETE BEFORE DELETE ON retained_documents BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_external_effect_events_UPDATE BEFORE UPDATE ON external_effect_events BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_external_effect_events_DELETE BEFORE DELETE ON external_effect_events BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_intake_holds_UPDATE BEFORE UPDATE ON intake_holds BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_intake_holds_DELETE BEFORE DELETE ON intake_holds BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_source_outcomes_UPDATE BEFORE UPDATE ON source_outcomes BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_source_outcomes_DELETE BEFORE DELETE ON source_outcomes BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_preview_files_UPDATE BEFORE UPDATE ON preview_files BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_preview_files_DELETE BEFORE DELETE ON preview_files BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_preview_generations_UPDATE BEFORE UPDATE ON preview_generations BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER immutable_preview_generations_DELETE BEFORE DELETE ON preview_generations BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER candidate_content_immutable BEFORE UPDATE OF id,identity,payload,content_hash ON candidates BEGIN SELECT RAISE(ABORT,'immutable_candidate_content'); END;
