import unittest
import json
import asyncio
from unittest.mock import patch, MagicMock
from src.functions.youtube_search.core.factory import YouTubeSearchFactory
from src.functions.youtube_search.core.service import YouTubeSearchService
from src.functions.youtube_search.core.config import YouTubeSearchRequest
from src.functions.youtube_search.functions.main import youtube_search_http

class TestYouTubeSearchEdgeCases(unittest.TestCase):

    def setUp(self):
        self.valid_payload = {
            "maxResults": 5,
            "q": "test",
            "type": "video",
            "credentials": {"key": "fake_key"}
        }

    def test_factory_invalid_max_results_low(self):
        """Test maxResults below minimum (1)."""
        payload = self.valid_payload.copy()
        payload["maxResults"] = 0
        with self.assertRaises(ValueError) as cm:
            YouTubeSearchFactory.create_request(payload)
        self.assertIn("Input should be greater than or equal to 1", str(cm.exception))

    def test_factory_invalid_max_results_high(self):
        """Test maxResults above maximum (50)."""
        payload = self.valid_payload.copy()
        payload["maxResults"] = 51
        with self.assertRaises(ValueError) as cm:
            YouTubeSearchFactory.create_request(payload)
        self.assertIn("Input should be less than or equal to 50", str(cm.exception))

    def test_factory_missing_credentials(self):
        """Test missing credentials."""
        payload = self.valid_payload.copy()
        del payload["credentials"]
        with self.assertRaises(ValueError) as cm:
            YouTubeSearchFactory.create_request(payload)
        self.assertIn("Field required", str(cm.exception))

    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_api_403_quota_exceeded(self, mock_client_cls):
        """Test Service handling of 403 Forbidden (Quota Exceeded)."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Quota Exceeded"
        mock_response.json.return_value = {
            "error": {
                "message": "The request cannot be completed because you have exceeded your <a href='/youtube/v3/getting-started#quota'>quota</a>."
            }
        }
        
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        request = YouTubeSearchRequest(**self.valid_payload)
        
        # We need to run the async function
        with self.assertRaises(RuntimeError) as cm:
            asyncio.run(YouTubeSearchService.search(request))
        
        self.assertIn("YouTube API Error (403)", str(cm.exception))
        self.assertIn("exceeded your", str(cm.exception))

    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_api_500_internal_error(self, mock_client_cls):
        """Test Service handling of 500 Internal Server Error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {} # Sometimes 500s don't have JSON bodies
        
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        request = YouTubeSearchRequest(**self.valid_payload)
        
        with self.assertRaises(RuntimeError) as cm:
            asyncio.run(YouTubeSearchService.search(request))
        
        self.assertIn("YouTube API Error (500)", str(cm.exception))

    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_malformed_response(self, mock_client_cls):
        """Test Service handling of malformed JSON response (missing 'items')."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Valid JSON but missing required fields for our models (though our model optional fields handle most, 
        # let's simulate a structure that breaks our expectations if we were strict, or check if it handles it gracefully)
        # Our Service currently expects 'items' to be in the response, but .get("items", []) handles missing key.
        # Let's verify it returns empty list if items is missing.
        mock_response.json.return_value = {
            "kind": "youtube#searchListResponse",
            "etag": "tag",
            # items missing
        }
        
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        request = YouTubeSearchRequest(**self.valid_payload)
        response = asyncio.run(YouTubeSearchService.search(request))
        
        self.assertEqual(response.items, [])

    @patch('src.functions.youtube_search.core.service.YouTubeTranscriptApi')
    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_fetch_transcripts_success(self, mock_client_cls, mock_api_cls):
        """Test Service fetching transcripts successfully."""
        # Setup API response with one video
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kind": "youtube#searchListResponse",
            "items": [
                {"id": {"videoId": "test_vid"}, "snippet": {}}
            ]
        }
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client
        
        # Setup transcript response
        # Mock instance returned by constructor
        mock_api_instance = mock_api_cls.return_value
        
        # Create mock objects for transcript snippets
        t1 = MagicMock()
        t1.text = "Hello"
        t1.start=0.0
        t1.duration=1.0
        mock_api_instance.fetch.return_value = [t1]

        # Request with fetchTranscripts=True (default) and NO proxy
        request = YouTubeSearchRequest(**self.valid_payload)
        response = asyncio.run(YouTubeSearchService.search(request))
        
        # Verify constructor called with no proxy
        mock_api_cls.assert_called_with(proxy_config=None)
        
        # Verify transcript was added
        self.assertEqual(len(response.items), 1)
        self.assertIsNotNone(response.items[0].get("transcript"))

    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_allowed_channel_filtering(self, mock_client_cls):
        """Test Filtering results by allowedChannelTitles."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kind": "youtube#searchListResponse",
            "items": [
                {"snippet": {"channelTitle": "Allowed Channel"}},
                {"snippet": {"channelTitle": "Spam Channel"}},
                {"snippet": {"channelTitle": "allowed channel"}}  # Case insensitive check
            ]
        }
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Filter for "Allowed Channel"
        payload = self.valid_payload.copy()
        payload["allowedChannelTitles"] = ["Allowed Channel"]
        # Disable transcripts for this test to avoid mocking it
        payload["fetchTranscripts"] = False
        
        request = YouTubeSearchRequest(**payload)
        response = asyncio.run(YouTubeSearchService.search(request))
        
        # Should keep items 0 and 2 (case-insensitive match)
        self.assertEqual(len(response.items), 2)
        self.assertEqual(response.items[0]["snippet"]["channelTitle"], "Allowed Channel")
        self.assertEqual(response.items[1]["snippet"]["channelTitle"], "allowed channel")

    @patch('src.functions.youtube_search.core.service.YouTubeTranscriptApi')
    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_fetch_transcripts_with_proxy(self, mock_client_cls, mock_api_cls):
        """Test Service fetching transcripts with proxy."""
        # Setup API response with one video
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kind": "youtube#searchListResponse",
            "items": [{"id": {"videoId": "test_vid"}, "snippet": {}}]
        }
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client
        
        # Mock API instance
        mock_api_instance = mock_api_cls.return_value
        t1 = MagicMock()
        t1.text = "Hello Proxy"
        mock_api_instance.fetch.return_value = [t1]

        # Request with proxy
        payload = self.valid_payload.copy()
        payload["proxyUrl"] = "http://myproxy.com:8080"
        request = YouTubeSearchRequest(**payload)
        
        response = asyncio.run(YouTubeSearchService.search(request))
        
        # Verify constructor called with proxy config
        # We need to check if one of the call args was a GenericProxyConfig
        # Since GenericProxyConfig is instantiated inside the method, we can't check identity easily 
        # unless we mock GenericProxyConfig too, but we can check if passed object has correct url.
        # But for simplicity, we mock GenericProxyConfig import in service.py if we want precise check.
        # Or we can just check call args.
        call_args = mock_api_cls.call_args
        self.assertIsNotNone(call_args)
        kwargs = call_args.kwargs
        proxy_config_arg = kwargs.get('proxy_config')
        self.assertIsNotNone(proxy_config_arg)
        self.assertEqual(proxy_config_arg.http_url, "http://myproxy.com:8080")

    @patch('src.functions.youtube_search.core.service.YouTubeTranscriptApi')
    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_fetch_transcripts_disabled(self, mock_client_cls, mock_api_cls):
        """Test Service skipping transcript fetch when disabled."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{"id": {"videoId": "test_vid"}}]
        }
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Disable transcripts
        payload = self.valid_payload.copy()
        payload["fetchTranscripts"] = False
        request = YouTubeSearchRequest(**payload)
        
        response = asyncio.run(YouTubeSearchService.search(request))
        
        # Verify constructor was NOT called (or fetch not called)
        # Note: Depending on where we instantitate, if outside loop vs inside.
        # Implementation instantiates `YouTubeTranscriptApi()` inside `_fetch_transcripts_for_items`
        # which is only called if fetchTranscripts is True.
        # So mocks should not be called at all.
        mock_api_cls.assert_not_called()
        
        # Verify transcript field is missing or None
        self.assertIsNone(response.items[0].get("transcript"))

    @patch('src.functions.youtube_search.core.service.YouTubeTranscriptApi')
    @patch('src.functions.youtube_search.core.service.httpx.AsyncClient')
    def test_service_fetch_transcripts_error_handled(self, mock_client_cls, mock_api_cls):
        """Test Service handling transcript fetch errors gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{"id": {"videoId": "test_vid"}}]
        }
        mock_client = MagicMock()
        mock_client.__aenter__.return_value.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Simulate transcript error on fetch
        mock_api_instance = mock_api_cls.return_value
        mock_api_instance.fetch.side_effect = Exception("Transcripts disabled")

        request = YouTubeSearchRequest(**self.valid_payload)
        response = asyncio.run(YouTubeSearchService.search(request))
        
        # Verify we still get the item, but transcript is None
        self.assertEqual(len(response.items), 1)
        self.assertIsNone(response.items[0].get("transcript"))

    @patch('src.functions.youtube_search.functions.main.YouTubeSearchFactory')
    def test_main_invalid_json_body(self, mock_factory):
        """Test Cloud Function entry point with invalid factory output (validation error)."""
        # Mocking the request
        mock_request = MagicMock()
        mock_request.get_json.return_value = {"bad": "data"}
        
        # Factory raises ValueError
        mock_factory.create_request.side_effect = ValueError("Invalid inputs")

        response = youtube_search_http(mock_request)
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid inputs", response.get_data(as_text=True))

    def test_main_empty_json(self):
        """Test Cloud Function with empty JSON."""
        mock_request = MagicMock()
        mock_request.get_json.return_value = None
        
        response = youtube_search_http(mock_request)
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid JSON payload", response.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
