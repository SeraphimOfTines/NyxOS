import unittest
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

class TestConfig(unittest.TestCase):
    def test_sanitize_ids_mixed_validity(self):
        """
        Verifies that the fixed sanitize_ids function correctly handles
        mixed valid and invalid entries, preserving the valid ones.
        """
        # Input: Mixed valid strings, invalid strings, and integers
        raw_ids = ["12345", "bad_id", 67890, "  99999  "]
        
        # Run the sanitization function from the fixed config module
        sanitized = config.sanitize_ids(raw_ids, "TEST_LIST")
        
        # Expected Output: [12345, 67890, 99999]
        # "bad_id" should be logged and skipped.
        
        self.assertIn(12345, sanitized)
        self.assertIn(67890, sanitized)
        self.assertIn(99999, sanitized)
        self.assertNotIn("bad_id", sanitized)
        self.assertNotIn("12345", sanitized) # Should be int now
        
        print(f"Sanitized Result: {sanitized}")

    def test_sanitize_ids_non_list(self):
        """Verifies handling of non-list input."""
        res = config.sanitize_ids("not a list", "TEST_LIST")
        self.assertEqual(res, [])

if __name__ == '__main__':
    unittest.main()