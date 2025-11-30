import pytest
from unittest.mock import MagicMock
from helpers import (
    get_safe_mime_type,
    matches_proxy_tag,
    clean_name_logic,
    sanitize_llm_response,
    restore_hyperlinks
)

class TestHelpers:

    def test_get_safe_mime_type(self):
        # Test 1: Priority - Extension
        mock_attachment_png = MagicMock()
        mock_attachment_png.filename = "test.png"
        mock_attachment_png.content_type = "text/plain" # Should be ignored
        assert get_safe_mime_type(mock_attachment_png) == "image/png"

        mock_attachment_jpg = MagicMock()
        mock_attachment_jpg.filename = "test.jpg"
        assert get_safe_mime_type(mock_attachment_jpg) == "image/jpeg"
        
        mock_attachment_webp = MagicMock()
        mock_attachment_webp.filename = "test.webp"
        assert get_safe_mime_type(mock_attachment_webp) == "image/webp"

        # Test 2: Trust Discord
        mock_attachment_discord = MagicMock()
        mock_attachment_discord.filename = "unknown.file"
        mock_attachment_discord.content_type = "image/gif"
        assert get_safe_mime_type(mock_attachment_discord) == "image/gif"

        # Test 3: System Registry Fallback
        # Depending on the system running the test, 'mimetypes' might behave differently.
        # But generally, .gif maps to image/gif.
        mock_attachment_sys = MagicMock()
        mock_attachment_sys.filename = "test.gif"
        mock_attachment_sys.content_type = None
        # This assertion relies on mimetypes.guess_type returning image/gif for .gif
        # If it fails on some minimal environments, we might need to mock mimetypes.
        assert get_safe_mime_type(mock_attachment_sys) == "image/gif"

        # Test 4: Ultimate Fallback
        mock_attachment_fallback = MagicMock()
        mock_attachment_fallback.filename = "unknown.xyz"
        mock_attachment_fallback.content_type = "application/octet-stream"
        assert get_safe_mime_type(mock_attachment_fallback) == "image/png"

    def test_matches_proxy_tag(self):
        # Setup tags
        tags = [
            {'prefix': 'Seraph:', 'suffix': ''},
            {'prefix': '', 'suffix': '-Chiara'},
            {'prefix': '[', 'suffix': ']'}
        ]

        # Test Matches
        assert matches_proxy_tag("Seraph: Hello", tags) is True
        assert matches_proxy_tag("Hello -Chiara", tags) is True
        assert matches_proxy_tag("[Hello]", tags) is True
        
        # Test whitespace handling
        assert matches_proxy_tag("  Seraph: Hello  ", tags) is True

        # Test Non-matches
        assert matches_proxy_tag("Hello World", tags) is False
        assert matches_proxy_tag("Seraph Hello", tags) is False # Missing colon
        assert matches_proxy_tag("Hello Chiara", tags) is False # Missing dash

    def test_clean_name_logic(self):
        # Test removal of system tags
        # assert clean_name_logic("Seraph [The AI]", "Seraph") == "The AI" # Removed incorrect assumption
        
        # Case 1: System tag is substring
        assert clean_name_logic("SeraphimBot", "Seraphim") == "Bot"

        # Case 2: Bracket removal
        assert clean_name_logic("Seraph [The AI]") == "Seraph"
        assert clean_name_logic("User (she/her)") == "User"
        assert clean_name_logic("Name <Tag>") == "Name"

        # Case 3: Both
        # "Seraph [The AI]", tag="Seraph" -> "[The AI]" -> "" (empty string? let's check)
        # Logic: name = name.replace(system_tag, "") -> " [The AI]"
        # Then re.sub removes brackets -> "" -> strip() -> ""
        assert clean_name_logic("Seraph [The AI]", "Seraph") == "" 

        # Case 4: No tags
        assert clean_name_logic("JustName") == "JustName"

    def test_sanitize_llm_response(self):
        # Test 1: Leading headers
        assert sanitize_llm_response("# Hello") == "Hello"
        assert sanitize_llm_response("### Title") == "Title"
        
        # Test 2: Flavor text
        assert sanitize_llm_response("Hello (Not Seraphim)") == "Hello"
        # Depending on config values mocked or actual. Assuming defaults or what helper imports.
        # Ideally we should mock config, but helpers imports config. 
        # Let's rely on the hardcoded replacements in the function first (Not Seraphim).
        
        # Test 3: Reply context
        assert sanitize_llm_response("Hello\n(re: User)") == "Hello"

    def test_restore_hyperlinks(self):
        # Test 1: Basic transformation
        assert restore_hyperlinks("(Google)(https://google.com)") == "[Google](https://google.com)"
        
        # Test 2: Nested parens in title? regex is `(.+?)` so it stops at first )
        # "(Title with (parens))(url)" -> match `Title with (parens` ? No, `Title with (parens` contains `)`
        # The regex is `\((.+?)\)((https?://[^\s)]+))\)`
        # If text is `(Title)(url)` -> matches.
        
        # Test 3: Normal text with parens
        text = "This is (normal text) and (another)"
        assert restore_hyperlinks(text) == text
        
        # Test 4: Mixed
        text = "Check (This)(https://link.com) out."
        assert restore_hyperlinks(text) == "Check [This](https://link.com) out."
