import pytest
from unittest.mock import MagicMock
import helpers
import config

@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 12345
    user.roles = []
    return user

def test_is_admin_user_id(mock_user):
    # Setup config
    original_admin_ids = config.ADMIN_USER_IDS
    config.ADMIN_USER_IDS = [12345]
    
    try:
        assert helpers.is_admin(mock_user) == True
        assert helpers.is_admin(12345) == True
        assert helpers.is_admin("12345") == True
    finally:
        config.ADMIN_USER_IDS = original_admin_ids

def test_is_admin_role_id(mock_user):
    # Setup config
    original_admin_roles = config.ADMIN_ROLE_IDS
    config.ADMIN_ROLE_IDS = [999]
    
    role = MagicMock()
    role.id = 999
    mock_user.roles = [role]
    
    try:
        assert helpers.is_admin(mock_user) == True
    finally:
        config.ADMIN_ROLE_IDS = original_admin_roles

def test_not_admin(mock_user):
    # Setup config
    original_admin_ids = config.ADMIN_USER_IDS
    original_admin_roles = config.ADMIN_ROLE_IDS
    config.ADMIN_USER_IDS = [99999]
    config.ADMIN_ROLE_IDS = [88888]
    
    try:
        assert helpers.is_admin(mock_user) == False
        assert helpers.is_admin(12345) == False
    finally:
        config.ADMIN_USER_IDS = original_admin_ids
        config.ADMIN_ROLE_IDS = original_admin_roles

def test_is_authorized_still_works(mock_user):
    # Ensure is_authorized still works for special users who aren't admins
    original_special = config.SPECIAL_ROLE_IDS
    config.SPECIAL_ROLE_IDS = [777]
    
    role = MagicMock()
    role.id = 777
    mock_user.roles = [role]
    
    try:
        assert helpers.is_authorized(mock_user) == True
        assert helpers.is_admin(mock_user) == False # Special is not Admin
    finally:
        config.SPECIAL_ROLE_IDS = original_special
