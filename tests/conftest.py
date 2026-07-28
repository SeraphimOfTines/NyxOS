import pytest
import memory_manager
import services

@pytest.fixture(autouse=True)
def clean_globals():
    # Store original
    original_cache = memory_manager._ALLOWED_CHANNELS_CACHE
    original_service = getattr(services, 'service', None)
    
    yield
    
    # Restore
    memory_manager._ALLOWED_CHANNELS_CACHE = None
    if original_service is not None:
        services.service = original_service
