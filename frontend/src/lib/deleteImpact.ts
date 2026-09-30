/** Above this many affected records (or any dependent child), a delete is
 * treated as high-impact: the confirm button in `ConfirmDialog` stays
 * disabled until the user types a confirmation value, instead of a single
 * click. Shared across every destructive delete flow (schemas, collections,
 * records) so the threshold — and what counts as "risky" — stays one
 * decision, not one per page. */
export const HIGH_IMPACT_RECORD_THRESHOLD = 25
