import unittest
from unittest.mock import MagicMock
import helpers
import config

class TestIsAdmin(unittest.TestCase):
    def setUp(self):
        # Mock config
        self.original_admin_users = config.ADMIN_USER_IDS
        self.original_admin_roles = config.ADMIN_ROLE_IDS
        self.original_special_roles = config.SPECIAL_ROLE_IDS
        
        config.ADMIN_USER_IDS = [123]
        config.ADMIN_ROLE_IDS = [456]
        config.SPECIAL_ROLE_IDS = [789]

    def tearDown(self):
        config.ADMIN_USER_IDS = self.original_admin_users
        config.ADMIN_ROLE_IDS = self.original_admin_roles
        config.SPECIAL_ROLE_IDS = self.original_special_roles

    def test_is_admin_user_id(self):
        user = MagicMock()
        user.id = 123
        self.assertTrue(helpers.is_admin(user))
        self.assertTrue(helpers.is_authorized(user))

    def test_is_admin_role_id(self):
        user = MagicMock()
        user.id = 999
        role = MagicMock()
        role.id = 456
        user.roles = [role]
        self.assertTrue(helpers.is_admin(user))
        self.assertTrue(helpers.is_authorized(user))

    def test_is_special_role_id(self):
        user = MagicMock()
        user.id = 888
        role = MagicMock()
        role.id = 789
        user.roles = [role]
        
        # Crucial test: Should NOT be admin, but SHOULD be authorized
        self.assertFalse(helpers.is_admin(user), "Special role should not be admin")
        self.assertTrue(helpers.is_authorized(user), "Special role should be authorized")

    def test_random_user(self):
        user = MagicMock()
        user.id = 111
        role = MagicMock()
        role.id = 222
        user.roles = [role]
        
        self.assertFalse(helpers.is_admin(user))
        self.assertFalse(helpers.is_authorized(user))

if __name__ == '__main__':
    unittest.main()