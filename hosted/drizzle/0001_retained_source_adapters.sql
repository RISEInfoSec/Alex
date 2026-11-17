CREATE TABLE `adapter_captures` (
	`id` text PRIMARY KEY NOT NULL,
	`source` text NOT NULL,
	`capture_hash` text NOT NULL,
	`capture` text NOT NULL,
	`status` text NOT NULL,
	`reason` text
);
--> statement-breakpoint
CREATE TABLE `adapter_results` (
	`capture_id` text NOT NULL,
	`position` integer NOT NULL,
	`result` text NOT NULL,
	`result_hash` text NOT NULL,
	PRIMARY KEY(`capture_id`, `position`),
	FOREIGN KEY (`capture_id`) REFERENCES `adapter_captures`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `pilot_outcomes` (
	`provider` text PRIMARY KEY NOT NULL,
	`receipt` text NOT NULL,
	`receipt_hash` text NOT NULL,
	FOREIGN KEY (`provider`) REFERENCES `pilot_reservations`(`provider`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `pilot_reservations` (
	`provider` text PRIMARY KEY NOT NULL,
	`request` text NOT NULL,
	`at` integer NOT NULL
);
--> statement-breakpoint
CREATE TRIGGER adapter_captures_no_update BEFORE UPDATE ON adapter_captures BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER adapter_captures_no_delete BEFORE DELETE ON adapter_captures BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER adapter_results_no_update BEFORE UPDATE ON adapter_results BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER adapter_results_no_delete BEFORE DELETE ON adapter_results BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER pilot_reservations_no_update BEFORE UPDATE ON pilot_reservations BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER pilot_reservations_no_delete BEFORE DELETE ON pilot_reservations BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER pilot_outcomes_no_update BEFORE UPDATE ON pilot_outcomes BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
--> statement-breakpoint
CREATE TRIGGER pilot_outcomes_no_delete BEFORE DELETE ON pilot_outcomes BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END;
