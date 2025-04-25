# app/services/base_service.py
from typing import Optional, Dict, Any
import httpx # Py lib that helps outgoing reqs to other services(OpenAI, Twilio, SendGrid API reqs)
from app.core.config import settings
import logging 

logger = logging.getLogger(__name__)


# foundational component that provides common HTTP functionality for API outgoing 
class BaseAPIService:
    """
    Base class for API services providing common functionality
    for handling API requests and responses.
    """
    def __init__(self):
        self.timeout = httpx.Timeout(60.0) # timeout config for a req 
        self._client: Optional[httpx.AsyncClient] = None # HTTP client instance for comms and network resources

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
    url: str, # outgoing API endpoint 
    headers: Dict[str, str],
    data: Optional[Dict[str, Any]] = None, # JSON payload for POST reqs
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
                json=data,  
                params=params
            )
            response.raise_for_status() # raise an error if the response status code is not 200-299
            
            return response.json()
        
        except httpx.HTTPStatusError as e: # The request reached the server, but the server returned an error
            logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            raise

        except Exception as e: # catch all
            logger.error(f"Request Error: {str(e)}")
            raise