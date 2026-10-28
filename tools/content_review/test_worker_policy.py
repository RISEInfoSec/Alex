import unittest
from worker_policy import plan_refill

class RollingBufferTests(unittest.TestCase):
    def test_strict_low_watermark(self):
        self.assertEqual(plan_refill(99)['minimum_new_candidates'],151)
        self.assertEqual(plan_refill(100)['minimum_new_candidates'],0)
        self.assertFalse(plan_refill(100)['global_refill_triggered'])
    def test_no_source_reserve(self):
        for count in (0,4,5,10):
            result=plan_refill(230,count)
            self.assertFalse(result['soups_refill_triggered'])
            self.assertEqual(result['soups_candidates_needed'],0)
            self.assertEqual(result['minimum_new_candidates'],0)
    def test_shared_deficit_is_source_independent(self):
        self.assertEqual(plan_refill(50,0)['minimum_new_candidates'],200)
        self.assertEqual(plan_refill(50,10)['minimum_new_candidates'],200)
    def test_empty_buffer_and_invalid_counts(self):
        self.assertEqual(plan_refill(0)['minimum_new_candidates'],250)
        with self.assertRaises(ValueError):plan_refill(-1)

if __name__=='__main__':unittest.main()
