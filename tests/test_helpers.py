import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import helpers
import config

class TestHelpers(unittest.TestCase):

    # --- get_safe_mime_type ---
    def test_get_safe_mime_type_extensions(self):
        """Verify correct MIME return for standard extensions."""
        mock_att = MagicMock()
        
        mock_att.filename = "test.png"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/png")
        
        mock_att.filename = "test.jpg"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/jpeg")
        
        mock_att.filename = "test.jpeg"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/jpeg")
        
        mock_att.filename = "test.webp"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/webp")

    def test_get_safe_mime_type_trust_discord(self):
        """Verify fallback to content_type attribute if extension is missing/weird."""
        mock_att = MagicMock()
        mock_att.filename = "unknown_file"
        mock_att.content_type = "image/gif"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/gif")

    def test_get_safe_mime_type_fallback(self):
        """Verify default to image/png for unknown types."""
        mock_att = MagicMock()
        mock_att.filename = "random.exe"
        mock_att.content_type = "application/octet-stream"
        self.assertEqual(helpers.get_safe_mime_type(mock_att), "image/png")

    # --- matches_proxy_tag ---
    def test_matches_proxy_tag_prefix(self):
        """Test matching with prefix only."""
        tags = [{'prefix': 'Seraph:', 'suffix': None}]
        self.assertTrue(helpers.matches_proxy_tag("Seraph: Hello", tags))
        self.assertFalse(helpers.matches_proxy_tag("Hello there", tags))

    def test_matches_proxy_tag_suffix(self):
        """Test matching with suffix only."""
        tags = [{'prefix': None, 'suffix': '-Chiara'}]
        self.assertTrue(helpers.matches_proxy_tag("Hello -Chiara", tags))
        self.assertFalse(helpers.matches_proxy_tag("Hello there", tags))

    def test_matches_proxy_tag_both(self):
        """Test matching with both brackets."""
        tags = [{'prefix': '[', 'suffix': ']'}]
        self.assertTrue(helpers.matches_proxy_tag("[Hello]", tags))
        self.assertFalse(helpers.matches_proxy_tag("Hello]", tags))
        self.assertFalse(helpers.matches_proxy_tag("[Hello", tags))

    def test_matches_proxy_tag_empty_check(self):
        """Test non-matches and empty tags."""
        tags = []
        self.assertFalse(helpers.matches_proxy_tag("Anything", tags))

    # --- clean_name_logic ---
    def test_clean_name_logic(self):
        """Verify removal of system tags and bracketed text from names."""
        self.assertEqual(helpers.clean_name_logic("Seraph [The AI]", None), "Seraph")
        self.assertEqual(helpers.clean_name_logic("John (Doe)", None), "John")
        self.assertEqual(helpers.clean_name_logic("Jane <Admin>", None), "Jane")
        self.assertEqual(helpers.clean_name_logic("Bob {Builder}", None), "Bob")
        self.assertEqual(helpers.clean_name_logic("Alice |Dev|", None), "Alice")
        self.assertEqual(helpers.clean_name_logic("Miko ⛩Shrine⛩", None), "Miko")

    def test_clean_name_logic_system_tag(self):
        """Verify removal of specific system tags."""
        tag = " [SYS]"
        self.assertEqual(helpers.clean_name_logic("User [SYS]", tag), "User")
        # Test if tag is just string
        self.assertEqual(helpers.clean_name_logic("User [SYS]", "[SYS]"), "User")
    
    def test_clean_name_logic_mixed_brackets(self):
        """Verify current regex behavior on mixed brackets (edge case)."""
        # The current regex allows mixed start/end brackets. 
        # This test documents that behavior.
        self.assertEqual(helpers.clean_name_logic("Test [Mix}", None), "Test")

    # --- sanitize_llm_response ---
    def test_sanitize_llm_response(self):
        """Verify removal of markdown headers, flavor text, and reply context."""
        # Mock config values used in sanitization
        with patch('config.ADMIN_FLAVOR_TEXT', " (Seraph)"), \
             patch('config.SPECIAL_FLAVOR_TEXT', " (Chiara)"):
            
            # Headers
            self.assertEqual(helpers.sanitize_llm_response("# Hello"), "Hello")
            self.assertEqual(helpers.sanitize_llm_response("## Hello"), "Hello")
            
            # Flavor Text
            self.assertEqual(helpers.sanitize_llm_response("Hello (Seraph)"), "Hello")
            self.assertEqual(helpers.sanitize_llm_response("Hello (Chiara)"), "Hello")
            self.assertEqual(helpers.sanitize_llm_response("Hello (Not Seraphim)"), "Hello")
            
            # Reply Context
            self.assertEqual(helpers.sanitize_llm_response("Hello (re: User)"), "Hello")
            
            # Combined
            raw = "# Hello (Seraph) (re: Bob)"
            self.assertEqual(helpers.sanitize_llm_response(raw), "Hello")

    def test_sanitize_llm_response_empty(self):
        self.assertEqual(helpers.sanitize_llm_response(None), "")
        self.assertEqual(helpers.sanitize_llm_response(""), "")

    # --- restore_hyperlinks ---
    def test_restore_hyperlinks(self):
        """Verify transformation of (Title)(URL) -> [Title](URL)."""
        text = "Check this (Google)(https://google.com) out."
        expected = "Check this [Google](https://google.com) out."
        self.assertEqual(helpers.restore_hyperlinks(text), expected)

    def test_restore_hyperlinks_nested(self):
        """Ensure normal text with parentheses isn't broken."""
        text = "This is (just text) and (Another)(http://site.com)."
        expected = "This is (just text) and [Another](http://site.com)."
        self.assertEqual(helpers.restore_hyperlinks(text), expected)

    def test_restore_hyperlinks_invalid_url(self):
        """Ensure it doesn't transform if the URL doesn't start with http/https."""
        text = "Check (This)(ftp://file) out."
        self.assertEqual(helpers.restore_hyperlinks(text), text)
        
        text = "Check (This)(not a url) out."
        self.assertEqual(helpers.restore_hyperlinks(text), text)

    def test_restore_hyperlinks_empty(self):
        self.assertEqual(helpers.restore_hyperlinks(None), "")

if __name__ == '__main__':
    unittest.main()