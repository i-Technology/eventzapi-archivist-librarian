
import tempfile
import unittest
from pathlib import Path

from y_inventory import YInventory, InventoryError


class TestYInventory(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.y = self.root / "cloud_y"
        self.y.mkdir()

        self.checkpoint = (
            self.root / "checkpoints" / "inventory.json"
        )

        self.inventory = YInventory(
            self.y, self.checkpoint
        )

        for i in range(100):
            (self.y / f"{i:04d}.tuple").write_bytes(
                f"immutable tuple {i}".encode()
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_inventory(self):
        self.inventory.create_checkpoint()

        result = self.inventory.verify()

        self.assertTrue(result["complete"])
        self.assertEqual(result["expected_count"], 100)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["corrupted"], [])

    def test_detect_missing_tuple(self):
        self.inventory.create_checkpoint()

        (self.y / "0042.tuple").unlink()

        result = self.inventory.verify()

        self.assertFalse(result["complete"])
        self.assertEqual(
            result["missing"], ["0042.tuple"]
        )

    def test_detect_corrupted_tuple(self):
        self.inventory.create_checkpoint()

        (self.y / "0042.tuple").write_bytes(
            b"damaged contents"
        )

        result = self.inventory.verify()

        self.assertFalse(result["complete"])
        self.assertEqual(
            result["corrupted"], ["0042.tuple"]
        )

    def test_detect_multiple_missing_tuples(self):
        self.inventory.create_checkpoint()

        for i in (10, 20, 30):
            (self.y / f"{i:04d}.tuple").unlink()

        result = self.inventory.verify()

        self.assertEqual(
            result["missing"],
            ["0010.tuple", "0020.tuple", "0030.tuple"],
        )

    def test_new_tuple_does_not_invalidate_checkpoint(self):
        self.inventory.create_checkpoint()

        (self.y / "0100.tuple").write_bytes(
            b"new tuple"
        )

        result = self.inventory.verify()

        self.assertTrue(result["complete"])
        self.assertEqual(
            result["extra"], ["0100.tuple"]
        )

    def test_detect_modified_checkpoint(self):
        self.inventory.create_checkpoint()

        self.checkpoint.write_bytes(
            self.checkpoint.read_bytes() + b"damage"
        )

        with self.assertRaises(
            (InventoryError, ValueError)
        ):
            self.inventory.verify()

    def test_refuse_checkpoint_overwrite(self):
        self.inventory.create_checkpoint()

        with self.assertRaises(InventoryError):
            self.inventory.create_checkpoint()

    def test_checkpoint_outside_y(self):
        with self.assertRaises(InventoryError):
            YInventory(
                self.y,
                self.y / "inventory.json",
            )


if __name__ == "__main__":
    unittest.main()
