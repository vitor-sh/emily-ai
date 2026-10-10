import unittest
import numpy as np
from refine_streaming import operating_point, aligned_windows

class RefinementChecks(unittest.TestCase):
    def test_overlap_cannot_be_misreported_as_success(self):
        point = operating_point([dict(positive=True,score=.9),dict(positive=False,score=.95)])
        self.assertEqual(point['recall'],0)
        self.assertEqual(point['false_positive_rate'],0)
    def test_saturation_remains_failure(self):
        point = operating_point([dict(positive=True,score=1.),dict(positive=False,score=1.)])
        self.assertEqual(point['false_positive_rate'],1.)
    def test_fine_quantized_boundary_is_considered(self):
        point = operating_point([dict(positive=True,score=.997),dict(positive=False,score=.996)])
        self.assertEqual(point['recall'],1.)
        self.assertEqual(point['false_positive_rate'],0.)
    def test_reference_window_shape_and_stride(self):
        features = np.tile(np.arange(231,dtype=np.float32)[:,None],(1,40))
        windows = aligned_windows(features,222)
        self.assertEqual(windows.shape,(4,222,40))
        np.testing.assert_array_equal(windows[:,0,0],[1,4,7,10])
        self.assertTrue(np.all(windows[:,-1,:]==0))

if __name__=='__main__':
    unittest.main()
