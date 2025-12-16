import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import shutil
import unittest
from datetime import datetime, timedelta
import config
from self_reflection import gather_logs_for_date

class TestReflection(unittest.TestCase):
    def setUp(self):
        self.test_logs_dir = os.path.join(os.path.dirname(__file__), "test_logs")
        if os.path.exists(self.test_logs_dir):
            shutil.rmtree(self.test_logs_dir)
        os.makedirs(self.test_logs_dir)
        
        # Mock config
        self.original_logs_dir = config.LOGS_DIR
        config.LOGS_DIR = self.test_logs_dir

    def tearDown(self):
        config.LOGS_DIR = self.original_logs_dir
        if os.path.exists(self.test_logs_dir):
            shutil.rmtree(self.test_logs_dir)

    def create_log(self, date_str, content):
        d_path = os.path.join(self.test_logs_dir, date_str)
        os.makedirs(d_path, exist_ok=True)
        with open(os.path.join(d_path, "channel.log"), "w") as f:
            f.write(content)

    def test_gather_logs_for_date(self):
        # Create logs for 3 days
        self.create_log("2025-12-14", "Log from the 14th")
        self.create_log("2025-12-15", "Log from the 15th")
        
        # 1. Gather 14th
        dt = datetime(2025, 12, 14, 0, 0, 0)
        logs = gather_logs_for_date(dt)
        self.assertIn("Log from the 14th", logs)
        self.assertNotIn("Log from the 15th", logs)
        
        # 2. Gather 15th
        dt = datetime(2025, 12, 15, 0, 0, 0)
        logs = gather_logs_for_date(dt)
        self.assertIn("Log from the 15th", logs)
        
        # 3. Gather 16th (Missing)
        dt = datetime(2025, 12, 16, 0, 0, 0)
        logs = gather_logs_for_date(dt)
        self.assertIsNone(logs)

if __name__ == '__main__':
    unittest.main()
