"""Shared rolling-buffer policy; never performs approval or publication."""
def plan_refill(ready_total, soups_ready_batches=0):
    # Second argument is retained for older callers; no source reserve is applied.
    if not isinstance(ready_total, int) or not isinstance(soups_ready_batches, int) or min(ready_total, soups_ready_batches) < 0:
        raise ValueError('Counts must be non-negative integers')
    deficit = 250 - ready_total if ready_total < 100 else 0
    return dict(global_refill_triggered=ready_total < 100,
                soups_refill_triggered=False,
                soups_candidates_needed=0,
                minimum_new_candidates=deficit,
                global_target=250, global_low_watermark=100,
                soups_min_ready_batches=0)
