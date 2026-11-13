'use strict';

// Resolve an intake reservation without promoting it into an editorial queue.
// Reserved identities are accepted only for SOUPS and only when they remain
// unique in the complete current manifest. Callers must still fence and check
// the live decision snapshot before committing any evidence.
function identity(collection, row, manifest) {
  const positive = value => Number.isSafeInteger(value) && value > 0;
  if (!row || typeof row !== 'object' || !manifest || !Array.isArray(manifest.records) ||
      !Array.isArray(manifest.preflight_records ?? [])) throw Error('Review identity inventory unavailable');
  let number = row.review_number, batch = row.review_batch ?? row.batch;
  if (collection === 'soups' && number == null) {
    number = row.reserved_review_number;
    batch = row.reserved_review_batch;
    if (!positive(number) || !positive(batch) ||
        (row.review_batch != null && row.review_batch !== batch) ||
        (row.batch != null && row.batch !== batch)) throw Error('Invalid SOUPS intake reservation');
    const rows = [...manifest.records, ...(manifest.preflight_records ?? [])];
    const collisions = rows.filter(other => other &&
      (other.review_number === number || other.reserved_review_number === number));
    if (collisions.length !== 1 || collisions[0].candidate_id !== row.candidate_id)
      throw Error('SOUPS intake reservation is not unique');
  }
  if (!positive(number)) throw Error('Review number unavailable');
  batch ??= collection === 'soups' ? (number <= 100 ? Math.ceil(number / 20) :
    number <= 118 ? 6 : 7 + Math.floor((number - 119) / 20)) : Math.ceil(number / 20);
  if (!positive(batch)) throw Error('Review batch unavailable');
  return {number, batch};
}
module.exports = {identity};
