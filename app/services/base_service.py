# app/services/base_service.py
from typing import Optional, Dict, Any
import httpx
from app.core.config import settings
import logging 
logger = logging.getLogger(__name__)



class BaseAPIService:
    """
    Base class for API services providing common functionality
    for handling API requests and responses.
    """

    def __init__(self):
        self.timeout = httpx.Timeout(30.0)
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """
        Returns an HTTP client with proper configuration.
        Creates a new client if none exists.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        """Closes the HTTP client connection."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def make_request(
    self,
    method: str,
    url: str,
    headers: Dict[str, str],
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
        """
        Makes an HTTP request with proper error handling and logging.
        """
        client = await self.get_client()
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=data,  # httpx uses 'json' parameter to automatically handle JSON encoding
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Request Error: {str(e)}")
            raise