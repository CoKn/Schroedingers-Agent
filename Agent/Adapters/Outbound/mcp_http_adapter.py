# LLM/Adapters/Outbound/mcp_http_adpater.py
import logging
from typing import Optional, Dict, Any
import asyncio

from mcp.client.streamable_http import streamablehttp_client
from ._base_mcp_client import _BaseMCPClient
from .mcp_http_auth import handle_callback, handle_redirect, InMemoryTokenStorage

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientMetadata


logger = logging.getLogger(__name__)

oauth_queue: asyncio.Queue[tuple[str, Optional[str]]] = asyncio.Queue()

async def handle_redirect(auth_url: str) -> None:
    # Log the URL so you can click it in your logs (or forward it to your UI)
    logger.warning("MCP OAuth redirect: %s", auth_url)

async def handle_callback() -> tuple[str, Optional[str]]:
    # Wait for the FastAPI route to push (code, state)
    return await oauth_queue.get()

class MCPHttpClient(_BaseMCPClient):
    async def connect(self, url: str, auth_config: dict | None = None):
        self._resource = url.rstrip("/")
        auth_provider = None

        # OAuth
        if auth_config and auth_config.get("type") in ("oauth", "oauth_browser"):
            base_server = self._resource[:-4] if self._resource.endswith("/mcp") else self._resource

            storage: TokenStorage = auth_config.get("storage") or InMemoryTokenStorage()
            client_name = auth_config.get("client_name", "My MCP Client")
            redirect_uri = auth_config.get("redirect_uri", "http://localhost:8080/mcp/oauth/callback")
            scope = auth_config.get("scope", "user")

            auth_provider = OAuthClientProvider(
                server_url=base_server,
                client_metadata=OAuthClientMetadata(
                    client_name=client_name,
                    redirect_uris=[redirect_uri],
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    scope=scope,
                ),
                storage=storage,
                redirect_handler=handle_redirect,
                callback_handler=handle_callback,
            )

        headers: Dict[str, str] = {}
        if auth_config and auth_config.get("type") in ("bearer", "api_key") and auth_config.get("token"):
            headers["Authorization"] = f"Bearer {auth_config['token']}"

        try:
            transport = streamablehttp_client(url=self._resource, auth=auth_provider, headers=headers or None)
        except TypeError:
            transport = streamablehttp_client(url=self._resource, auth=auth_provider)

        await self.connect_transport(transport)
        logger.info("HTTP MCP client connected")

    async def disconnect(self):
        await super().disconnect()
        logger.info("HTTP MCP client disconnected")