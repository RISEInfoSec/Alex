"""Deterministic rolling-buffer policy; never performs approval or publication."""
def plan_refill(ready_total, soups_ready_batches):
    if not isinstance(ready_total, int) or not isinstance(soups_ready_batches, int) or min(ready_total, soups_ready_batches) < 0:
        raise ValueError('Counts must be non-negative integers')
    global_deficit = 250 - ready_total if ready_total < 100 else 0
    soups_deficit = max(0, 5 - soups_ready_batches) * 20
    return dict(global_refill_triggered=ready_total < 100,
                soups_refill_triggered=soups_ready_batches < 5,
                soups_candidates_needed=soups_deficit,
                minimum_new_candidates=max(global_deficit, soups_deficit),
                global_target=250, global_low_watermark=100,
                soups_min_ready_batches=5)

