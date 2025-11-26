import discord
from discord import app_commands
import os
import sys
import asyncio
import config
import helpers
import ui

# This file is intended to be loaded by NyxOS.py as a module to register the debug command.
# However, since NyxOS.py imports modules, we can inject this logic or manually add it.
# Given the request, the cleanest way is to add a new command logic to NyxOS.py dynamically 
# or just provide the code snippet to be added.

# Since I cannot dynamically edit the running process easily, I will provide the logic 
# to be added to NyxOS.py via the 'replace' tool in the next step.

# This file serves as the runner for the test suite if executed directly.
if __name__ == "__main__":
    print("running test suite...")
    import tests.test_suite
    result = tests.test_suite.run_suite()
    if result.wasSuccessful():
        sys.exit(0)
    else:
        sys.exit(1)
