import {sqliteTable,text,integer,real,uniqueIndex,primaryKey} from 'drizzle-orm/sqlite-core';
export const candidates=sqliteTable('candidates',{id:text('id').primaryKey(),identity:text('identity').notNull().unique(),payload:text('payload').notNull(),contentHash:text('content_hash').notNull(),state:text('state').notNull()});
export const aliases=sqliteTable('aliases',{identity:text('identity').primaryKey(),candidateId:text('candidate_id').notNull().references(()=>candidates.id)});
export const discoveries=sqliteTable('discoveries',{source:text('source').notNull(),receipt:text('receipt').notNull(),payloadHash:text('payload_hash').notNull(),candidateId:text('candidate_id').notNull().references(()=>candidates.id)},t=>[primaryKey({columns:[t.source,t.receipt]})]);
export const jobs=sqliteTable('jobs',{id:integer('id').primaryKey(),candidateId:text('candidate_id').notNull().references(()=>candidates.id),stage:text('stage').notNull(),status:text('status').notNull(),lease:text('lease'),leaseUntil:real('lease_until'),attempts:integer('attempts').notNull().default(0)},t=>[uniqueIndex('candidate_stage').on(t.candidateId,t.stage)]);
export const attempts=sqliteTable('attempt_events',{id:integer('id').primaryKey(),jobId:integer('job_id').notNull().references(()=>jobs.id),lease:text('lease').notNull(),event:text('event').notNull(),at:real('at').notNull(),detail:text('detail').notNull()});
export const checks=sqliteTable('checks',{candidateId:text('candidate_id').notNull().references(()=>candidates.id),contentHash:text('content_hash').notNull(),name:text('name').notNull(),result:text('result').notNull(),evidence:text('evidence').notNull()},t=>[primaryKey({columns:[t.candidateId,t.contentHash,t.name]})]);
export const decisions=sqliteTable('decisions',{id:text('id').primaryKey(),candidateId:text('candidate_id').notNull().unique().references(()=>candidates.id),contentHash:text('content_hash').notNull(),verdict:text('verdict').notNull(),actor:text('actor').notNull(),reason:text('reason').notNull(),at:real('at').notNull(),origin:text('origin').notNull()});
export const publications=sqliteTable('publications',{candidateId:text('candidate_id').primaryKey().references(()=>candidates.id),decisionId:text('decision_id').notNull().unique().references(()=>decisions.id),contentHash:text('content_hash').notNull(),record:text('record').notNull(),at:real('at').notNull()});
export const documents=sqliteTable('retained_documents',{candidateId:text('candidate_id').primaryKey().references(()=>candidates.id),contentHash:text('content_hash').notNull(),receipt:text('receipt').notNull(),receiptHash:text('receipt_hash').notNull()});
export const effects=sqliteTable('external_effects',{requestHash:text('request_hash').primaryKey(),request:text('request').notNull(),state:text('state').notNull(),token:text('token'),attempts:integer('attempts').notNull().default(0),response:text('response'),responseHash:text('response_hash'),notBefore:real('not_before').notNull().default(0),reason:text('reason').notNull()});
export const effectEvents=sqliteTable('external_effect_events',{id:integer('id').primaryKey(),requestHash:text('request_hash').notNull().references(()=>effects.requestHash),event:text('event').notNull(),receipt:text('receipt').notNull(),at:real('at').notNull()});
export const intakeHolds=sqliteTable('intake_holds',{receiptHash:text('receipt_hash').primaryKey(),source:text('source').notNull(),record:text('record').notNull(),reason:text('reason').notNull()});
export const outcomes=sqliteTable('source_outcomes',{receiptHash:text('receipt_hash').primaryKey(),source:text('source').notNull(),status:text('status').notNull(),discovered:integer('discovered').notNull(),held:integer('held').notNull()});
export const control=sqliteTable('runtime_control',{id:integer('id').primaryKey(),policyHash:text('policy_hash').notNull(),implementationHash:text('implementation_hash').notNull(),phase:text('phase').notNull(),ticks:integer('ticks').notNull(),maxTicks:integer('max_ticks').notNull(),deadline:real('deadline').notNull(),activeToken:text('active_token'),activeUntil:real('active_until'),interruptedLease:text('interrupted_lease'),interruptedJob:integer('interrupted_job'),replaysVerified:integer('replays_verified').notNull().default(0)});
export const receipts=sqliteTable('worker_receipts',{id:text('id').primaryKey(),scheduledTime:integer('scheduled_time').notNull(),cron:text('cron').notNull(),implementationHash:text('implementation_hash').notNull(),status:text('status').notNull(),completedJobs:integer('completed_jobs').notNull(),detail:text('detail').notNull()});
export const previewFiles=sqliteTable('preview_files',{generation:text('generation').notNull(),name:text('name').notNull(),body:text('body').notNull(),bodyHash:text('body_hash').notNull()},t=>[primaryKey({columns:[t.generation,t.name]})]);
export const previewGenerations=sqliteTable('preview_generations',{generation:text('generation').primaryKey(),manifest:text('manifest').notNull(),createdAt:real('created_at').notNull()});
export const previewCurrent=sqliteTable('preview_current',{id:integer('id').primaryKey(),generation:text('generation').notNull().references(()=>previewGenerations.generation)});
export const adapterCaptures = sqliteTable('adapter_captures', {
  id: text('id').primaryKey(),
  source: text('source').notNull(),
  captureHash: text('capture_hash').notNull(),
  capture: text('capture').notNull(),
  status: text('status').notNull(),
  reason: text('reason'),
});
export const adapterResults = sqliteTable('adapter_results', {
  captureId: text('capture_id').notNull().references(() => adapterCaptures.id),
  position: integer('position').notNull(),
  result: text('result').notNull(),
  resultHash: text('result_hash').notNull(),
}, table => [primaryKey({columns: [table.captureId, table.position]})]);
export const pilotReservations = sqliteTable('pilot_reservations', {
  provider: text('provider').primaryKey(),
  request: text('request').notNull(),
  at: integer('at').notNull(),
});
export const pilotOutcomes = sqliteTable('pilot_outcomes', {
  provider: text('provider').primaryKey().references(() => pilotReservations.provider),
  receipt: text('receipt').notNull(),
  receiptHash: text('receipt_hash').notNull(),
});
