import os
import sys

# Mock config.txt if missing to avoid errors
if not os.path.exists("config.txt"):
    with open("config.txt", "w") as f:
        f.write("BOT_ROLE_IDS = [123]\nADMIN_ROLE_IDS=[456]\nSPECIAL_ROLE_IDS=[789]")

import config

print(f"BOT_ROLE_IDS: {config.BOT_ROLE_IDS}")
print(f"ADMIN_ROLE_IDS: {config.ADMIN_ROLE_IDS}")
print(f"SPECIAL_ROLE_IDS: {config.SPECIAL_ROLE_IDS}")

trigger_roles = set(config.BOT_ROLE_IDS + config.ADMIN_ROLE_IDS + config.SPECIAL_ROLE_IDS)
print(f"TRIGGER_ROLES: {trigger_roles}")

# Mock Message
class MockRole:
    def __init__(self, id):
        self.id = id

class MockMessage:
    def __init__(self):
        self.role_mentions = []
        self.mentions = []
        self.content = ""

# Scenario 1: Tagging a Bot Role
msg = MockMessage()
msg.role_mentions = [MockRole(1443172515043217429)] # One of the IDs from config.txt
should_respond = False
if msg.role_mentions:
    for role in msg.role_mentions:
        if role.id in trigger_roles:
            should_respond = True
            break
print(f"Scenario 1 (Tag Bot Role 1443172515043217429): should_respond = {should_respond}")

# Scenario 2: Tagging a Random Role
msg.role_mentions = [MockRole(999999)]
should_respond = False
if msg.role_mentions:
    for role in msg.role_mentions:
        if role.id in trigger_roles:
            should_respond = True
            break
print(f"Scenario 2 (Tag Random Role 999999): should_respond = {should_respond}")
