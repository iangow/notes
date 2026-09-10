import unittest

from analyze_paired_timestamp_audit import zero_error_upper


class ZeroErrorTests(unittest.TestCase):
    def test_nonzero_bound_for_zero_observed_errors(self):
        e,v,ratio=zero_error_upper([(100000,1000),(200000,1000)],.9)
        self.assertGreater(e,0)
        self.assertLess(v,.9)
        self.assertGreater(ratio,e)
        self.assertLess(ratio,1)

    def test_census_and_unverifiable(self):
        self.assertEqual(zero_error_upper([(10,10)],1),(0.,1,0.))
        self.assertEqual(zero_error_upper([(100000,10)],0)[2],1.)


if __name__=='__main__':
    unittest.main()
