# Published corpus relevance audit — 28 October 2026

All3,644 public records at main commit8585d665b471363a8141b3bc9aa1f45edfc3fc15 were screened using complete stored titles and abstracts. Exact source hashes and one assessment per public identity were validated. No public records were changed or removed.

Final queue:714 entries in36 batches (35×20 plus14):274 apparently outside scope,262 borderline,178 with insufficient evidence. All173 speculative summaries starting “This paper appears to” require evidence review. The five environmental/gas booklets are included.2,930 records received no final relevance flag. These are screening recommendations, not deletion decisions or full-paper scientific reviews.

Raw first-pass and individual verification evidence, API response identities and usage are on branch codex/corpus-relevance-audit-20261028, config/corpus_relevance_audit/. Workflows40671199156 and40672964162 succeeded. The stronger individual verification pass covered1,213 disputed relevance/evidence records. Punctuation-only quotation differences were aligned against original source words; unresolved model quotations were replaced for display with explicitly identified exact stored-abstract excerpts. Quotation-format mistakes alone do not establish poor original evidence. Original model quotations remain in audit evidence.

The manifest preserves exact reviewed content, original public identity, category/investigation labels, evidence, recommendations and stable content hashes. Corpus-audit is separate from intake and never counts toward the250 buffer or requests import/classification/refill. In this collection approved means KEEP and rejected means REQUEST REMOVAL. Explicit user submissions persist in existing authenticated decision tables and create corpus_removal_review jobs only for requested removals. They do not directly delete records.

26 console tests, TypeScript checks and production build passed. Console source5c06b8ba2f3aab6e328d1a933ed182751f79a1ac deployed as version8. Browser preview was inaccessible and the production browser required sign-in, so signed-in UI interaction was not tested. Existing audience and all stored decisions were preserved.

Reported first-pass usage is a lower bound because usage from initial invalid-membership responses was not saved; continuation and verification usage were checkpointed. See config/corpus_relevance_audit_summary.json for recorded totals.
