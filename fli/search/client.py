from curl_cffi import requests
from ratelimit import limits, sleep_and_retry
from tenacity import retry, stop_after_attempt, wait_exponential

client = None


class Client:
    """Base HTTP client with rate limiting and retry functionality."""

    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }

    def __init__(self):
        """Initialize the client."""
        self._client = requests.Session()
        self._client.headers.update(self.DEFAULT_HEADERS)

    def __del__(self):
        """Cleanup client session."""
        if hasattr(self, "_client"):
            self._client.close()

    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(), reraise=True)
    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Make a rate-limited GET request with automatic retries.

        Args:
            url: The URL to request.
            **kwargs: Additional arguments to pass to the request.

        Returns:
            The response from the server.

        Raises:
            Exception: If the request fails after retries.
        """
        try:
            response = self._client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except Exception as e:
            raise Exception(f"GET request failed: {str(e)}") from e

    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(), reraise=True)
    def post(self, url: str, **kwargs) -> requests.Response:
        """
        Make a rate-limited POST request with automatic retries.

        Args:
            url: The URL to request.
            **kwargs: Additional arguments to pass to the request.

        Returns:
            The response from the server.

        Raises:
            Exception: If the request fails after retries.
        """
        try:
            response = self._client.post(url, **kwargs)
            response.raise_for_status()
            return response
        except Exception as e:
            raise Exception(f"POST request failed: {str(e)}") from e


def get_client() -> Client:
    """Get the shared HTTP client instance."""
    global client
    if not client:
        client = Client()
    return client
