import unittest
from worker_policy import plan_refill

class RollingBufferTests(unittest.TestCase):
    def test_strict_low_watermark(self):
        self.assertEqual(plan_refill(99,5)['minimum_new_candidates'],151)
        self.assertEqual(plan_refill(100,5)['minimum_new_candidates'],0)
        self.assertFalse(plan_refill(100,5)['global_refill_triggered'])
    def test_source_floor_is_independent(self):
        result=plan_refill(230,4)
        self.assertFalse(result['global_refill_triggered'])
        self.assertEqual(result['soups_candidates_needed'],20)
    def test_empty_buffer_and_invalid_counts(self):
        self.assertEqual(plan_refill(0,0)['minimum_new_candidates'],250)
        with self.assertRaises(ValueError):plan_refill(-1,5)

if __name__=='__main__':unittest.main()

