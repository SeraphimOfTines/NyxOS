import pytest
import sys
import os

# This test suite runner ensures all pytest-style tests in the tests/ directory
# can be executed from a single entry point if desired, though `pytest` CLI is preferred.

def run_suite():
    """Runs the full pytest suite."""
    # Add root directory to sys.path to ensure imports work
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(root_dir)
    
    print(f"🚀 Running Test Suite from: {root_dir}")
    
    # Invoke pytest
    # -v: Verbose
    # tests/: Target directory
    exit_code = pytest.main(["-v", "tests/"])
    
    sys.exit(exit_code)

if __name__ == "__main__":
    run_suite()