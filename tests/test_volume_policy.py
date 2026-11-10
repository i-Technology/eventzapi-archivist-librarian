
import sys
from pathlib import Path
import unittest
from volume_policy import Volume, VolumeState, Policy, evaluate, choose_successor

sys.path.insert(0, str(Path(__file__).resolve().parent))

GB = 1_000_000_000

class VolumePolicyTests(unittest.TestCase):
    def test_normal_append(self):
        d = evaluate(Volume('Y1', 100*GB, 30*GB, VolumeState.ACTIVE), GB)
        self.assertTrue(d.may_append)
        self.assertFalse(d.request_new_volume)

    def test_provisioning_warning(self):
        d = evaluate(Volume('Y1', 100*GB, 80*GB, VolumeState.ACTIVE), GB)
        self.assertTrue(d.may_append)
        self.assertTrue(d.request_new_volume)

    def test_crossing_95_percent_is_prevented(self):
        d = evaluate(Volume('Y1', 100*GB, 94*GB, VolumeState.ACTIVE), 2*GB)
        self.assertFalse(d.may_append)
        self.assertTrue(d.seal_volume)

    def test_exact_95_percent_allowed_then_sealed(self):
        v = Volume('Y1', 100*GB, 94*GB, VolumeState.ACTIVE)
        self.assertTrue(evaluate(v, GB).may_append)
        self.assertTrue(evaluate(Volume('Y1', 100*GB, 95*GB, VolumeState.ACTIVE), 1).seal_volume)

    def test_sealed_volume_remains_online_but_not_writable(self):
        d = evaluate(Volume('Y1', 100*GB, 95*GB, VolumeState.SEALED), 1)
        self.assertFalse(d.may_append)
        self.assertFalse(d.seal_volume)

    def test_successor_selection(self):
        vols = [Volume('Y1',100*GB,95*GB,VolumeState.SEALED),
                Volume('Y2',100*GB,0,VolumeState.STANDBY)]
        self.assertEqual(choose_successor(vols).name, 'Y2')

    def test_no_successor(self):
        self.assertIsNone(choose_successor([Volume('Y1',100*GB,95*GB,VolumeState.SEALED)]))

    def test_absolute_reserve(self):
        p = Policy(reserve_bytes=10*GB)
        d = evaluate(Volume('Y1',100*GB,89*GB,VolumeState.ACTIVE),2*GB,p)
        self.assertFalse(d.may_append)

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            Volume('Y1',100,101,VolumeState.ACTIVE)

if __name__ == '__main__':
    unittest.main(verbosity=2)
