# Agent/Adapters/Outbound/mcp_adapters.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, List, Any

from Agent.Adapters.Outbound.azure_openai_adapter import AzureOpenAIAdapter
from Agent.Adapters.Outbound.openai_adapter import OpenAIAdapter

from Agent.Adapters.Outbound.mcp_http_adapter import MCPHttpClient
from Agent.Adapters.Outbound.mcp_stdio_adapter import MCPStdioClient

import json
import logging
import asyncio
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def _is_oauth(auth: dict | None) -> bool:
    """Return True if the auth block indicates an interactive OAuth flow."""
    return bool(auth and auth.get("type") in ("oauth", "oauth_browser"))


class MCPAdapter(BaseModel):
    """
    Multi-server MCP adapter. Supports both HTTP (Streamable HTTP) and stdio transports.

    Notes:
    - For HTTP servers that use OAuth (e.g., Notion MCP at https://mcp.notion.com/mcp),
      we do NOT wrap connect() in a short asyncio.wait_for timeout because the SDK
      will run an interactive browser flow. Let it complete.
    - For API key / bearer configurations (non-interactive), we keep the shorter timeout.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Store multiple clients with their identifiers
    clients: Dict[str, Any] = {}
    tools_registry: List[Dict[str, Any]] = []
    llm: Optional[AzureOpenAIAdapter] | Optional[OpenAIAdapter] = None

    async def init(self, server_configs: List[Dict[str, Any]]):
        """
        Initialize connections to multiple MCP servers.

        Example servers_config:
        [
          {
            "Notion": {
              "type": "http",
              "url": "https://mcp.notion.com/mcp",
              "auth": {
                "type": "oauth",
                "client_name": "My Agent",
                "redirect_uri": "http://localhost:5173/callback",
                "scope": "user"
              }
            }
          },
          {
            "LocalTooling": {
              "type": "stdio",
              "path": "/path/to/server",
              "command": "uvx",
              "args": ["python", "-m", "my_mcp_server"],
              "env": {"FOO": "bar"}
            }
          }
        ]
        """
        logger.info(f"Initializing MCP adapter with {len(server_configs)} servers")

        for server_config in server_configs:
            server_name = list(server_config.keys())[0]
            conf = server_config[server_name]
            server_type = conf["type"]

            try:
                if server_type == "http":
                    client = MCPHttpClient()
                    auth_conf = conf.get("auth")

                    # For interactive OAuth flows, don't use a short timeout
                    if _is_oauth(auth_conf):
                        await client.connect(conf["url"], auth_config=auth_conf)
                    else:
                        # Non-interactive (bearer/api-key/etc.) can use a short timeout
                        try:
                            await asyncio.wait_for(
                                client.connect(conf["url"], auth_config=auth_conf),
                                timeout=30
                            )
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            logger.error("Timeout connecting to HTTP server %s", server_name)
                            try:
                                await client.disconnect()
                            except Exception:
                                pass
                            continue

                elif server_type == "stdio":
                    client = MCPStdioClient()
                    try:
                        await client.connect(conf)
                    except asyncio.TimeoutError:
                        logger.error("Timeout connecting to Stdio server %s", server_name)
                        # One retry with timeout, mirroring your original behavior
                        await asyncio.wait_for(client.connect(conf), timeout=30)
                        continue

                else:
                    logger.warning(f"Unknown server type: {server_type}")
                    continue

                # Record the connected client
                self.clients[server_name] = {
                    "client": client,
                    "type": server_type,
                    "config": conf
                }

                # Register this client's tools
                await self._register_tools_from_server(server_name, client, server_type)
                logger.info(f"Connected to {server_type} server: {server_name}")

            except Exception as e:
                logger.error(f"Failed to connect to server {server_name}: {e}", exc_info=True)
                # Ensure any half-open client is torn down
                try:
                    if server_name in self.clients and self.clients[server_name].get("client"):
                        await self.clients[server_name]["client"].disconnect()
                except Exception:
                    pass
                # Drop it from clients if present
                self.clients.pop(server_name, None)
                continue

    async def _register_tools_from_server(self, server_name: str, client: Any, transport: str):
        """Register tools from a specific server."""
        try:
            session = client.session
            if not session:
                logger.error(f"No valid session for server {server_name}")
                return

            # Try once, then optionally reconnect-and-retry. No custom token juggling.
            try:
                tools_response = await session.list_tools()
            except Exception as e:
                logger.debug(f"list_tools() failed for {server_name}: {e}", exc_info=True)
                # Attempt a single reconnect
                if await self.reconnect_server(server_name):
                    session = self.clients[server_name]["client"].session
                    tools_response = await session.list_tools()
                else:
                    raise

            # Register tools
            for tool in tools_response.tools:
                tool_entry = {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.inputSchema,
                    "server_id": server_name,
                    "session": session,
                    "transport": transport
                }
                self.tools_registry.append(tool_entry)

            logger.info(f"Registered {len(tools_response.tools)} tools from {server_name}")

        except Exception as e:
            logger.error(f"Failed to register tools from {server_name}: {e}", exc_info=True)

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        logger.info("Disconnecting from all MCP servers...")

        for server_name, server_info in list(self.clients.items()):
            try:
                await server_info["client"].disconnect()
                logger.info(f"Disconnected from {server_name}")
            except Exception as e:
                logger.error(f"Error disconnecting from {server_name}: {e}", exc_info=True)

        self.clients.clear()
        self.tools_registry.clear()

    async def reconnect_server(self, server_name: str) -> bool:
        """Reconnect to a specific server if connection is lost."""
        if server_name not in self.clients:
            logger.error(f"Server {server_name} not found in clients")
            return False

        server_info = self.clients[server_name]
        config = server_info["config"]

        try:
            # Disconnect existing connection
            try:
                await server_info["client"].disconnect()
            except Exception:
                pass

            # Create new client and reconnect
            if config["type"] == "http":
                client = MCPHttpClient()
                auth_conf = config.get("auth")
                if _is_oauth(auth_conf):
                    await client.connect(config["url"], auth_config=auth_conf)
                else:
                    await asyncio.wait_for(client.connect(config["url"], auth_config=auth_conf), timeout=30)
            elif config["type"] == "stdio":
                client = MCPStdioClient()
                # Original code had mixed usage of conf vs params; keep consistent with .init()
                await client.connect(config)
            else:
                logger.error(f"Unknown server type for reconnect: {config['type']}")
                return False

            # Update client reference
            self.clients[server_name]["client"] = client

            # Re-register tools
            await self._register_tools_from_server(server_name, client, config["type"])

            logger.info(f"Reconnected to {server_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to reconnect to {server_name}: {e}", exc_info=True)
            return False

    def get_available_tools(self) -> List[str]:
        """Get list of all available tool names."""
        return [tool["name"] for tool in self.tools_registry]

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Execute a registered tool by name and return its textual result."""
        tool_info = next((tool for tool in self.tools_registry if tool["name"] == name), None)
        if not tool_info:
            raise ValueError(f"Tool '{name}' not found")
        result = await tool_info["session"].call_tool(name, args)
        if hasattr(result, 'content'):
            if isinstance(result.content, list) and len(result.content) > 0:
                first_content = result.content[0]
                return first_content.text if hasattr(first_content, 'text') else str(first_content)
            return str(result.content)
        return str(result)
    
    async def startup_mcp(self):
        """Initialize MCP connections at startup"""
        try:
            servers_config = load_config("Agent/.config.json")
            await self.init(servers_config)
            logger.info("MCP startup completed successfully")
        except Exception as e:
            logger.error(f"MCP startup failed: {e}")
            raise

    def get_tools_json(self) -> List[Dict[str, Any]]:
        """Return JSON-serializable metadata for all registered tools.

        Filters out non-serializable objects like session references.

        Returns:
            List of dicts with keys: name, description, schema, server_id, transport
        """
        tools: List[Dict[str, Any]] = []
        for t in self.tools_registry:
            try:
                tools.append({
                    "name": t.get("name"),
                    "description": t.get("description"),
                    "schema": t.get("schema"),
                    "server_id": t.get("server_id"),
                    "transport": t.get("transport"),
                })
            except Exception:
                # Be resilient if any unexpected shape slips in
                continue
        return tools


def load_config(config_path: str = ".config.json") -> List[Dict[str, Any]]:
    """
    Load MCP server configuration from a JSON file.

    Args:
        config_path: Path to the configuration file (default: ".config.json")

    Returns:
        List of server configurations

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file contains invalid JSON
    """
    try:
        file_path = Path(config_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        config_data = json.loads(file_path.read_text())
        logger.info(f"Loaded configuration for {len(config_data)} servers from {config_path}")
        return config_data

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file {config_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {e}")
        raise
