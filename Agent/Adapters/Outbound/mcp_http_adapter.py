# LLM/Adapters/Outbound/mcp_http_adpater.py
import logging
from mcp.client.streamable_http import streamablehttp_client
from ._base_mcp_client import _BaseMCPClient

logger = logging.getLogger(__name__)

class MCPHttpClient(_BaseMCPClient):
    """MCP over HTTP using streamablehttp_client + ClientSession."""

    async def connect(self, url: str):
        transport = streamablehttp_client(url=url)
        await self.connect_transport(transport)
        logger.info("✅ HTTP MCP client connected")

    async def disconnect(self):
        await super().disconnect()
        logger.info("✅ HTTP MCP client disconnected")
