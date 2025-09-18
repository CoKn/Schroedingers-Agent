# LLM/Adapters/Outbound/mcp_stdio_adpater.py
import logging
from mcp.client.stdio import stdio_client
from mcp import StdioServerParameters
from ._base_mcp_client import _BaseMCPClient

logger = logging.getLogger(__name__)

class MCPStdioClient(_BaseMCPClient):
    """MCP over stdio using stdio_client + ClientSession."""

    async def connect(self, stdio_server_params: dict):
        params = StdioServerParameters(**stdio_server_params)
        transport = stdio_client(params)
        await self.connect_transport(transport)
        logger.info("✅ stdio MCP client connected")

    async def disconnect(self):
        await super().disconnect()
        logger.info("✅ stdio MCP client disconnected")
