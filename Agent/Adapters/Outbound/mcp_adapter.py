# Agent/Adapers/Outbound/mcp_adapters.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, List, Any
from Agent.Adapters.Outbound.azure_openai_adapter import AzureOpenAIAdapter
from Agent.Adapters.Outbound.mcp_http_adapter import MCPHttpClient
from Agent.Adapters.Outbound.mcp_stdio_adapter import MCPStdioClient

import os
import time
import json
import logging
import asyncio
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

class MCPAdapter(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Store multiple clients with their identifiers
    clients: Dict[str, Any] = {}
    tools_registry: List[Dict[str, Any]] = []
    llm: Optional[AzureOpenAIAdapter] = None
    
    async def init(self, server_configs: List[Dict[str, Any]]):
        """
        Initialize connections to multiple MCP servers.
        
        servers_config format:
        [
            {"name": {"type": "http", "url": "http://localhost:8081/mcp/"}},
            {"name": {{"type": "stdio", "path": "path to script", "command": "uvx", "args": [...], "env": {...}}} 
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
                    try: 
                        await asyncio.wait_for(client.connect(conf["url"]), timeout=30)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        logger.error("Timeout connecting to HTTP server %s", server_name)
                        await client.disconnect()
                        continue
                elif server_type == "stdio":
                    client = MCPStdioClient()
                    try:
                        await client.connect(conf)
                    except asyncio.TimeoutError:
                        logger.error("Timeout connecting to Stdio server %s", server_name)
                        await asyncio.wait_for(client.connect(conf), timeout=30)
                        continue
                else:
                    logger.warning(f"Unknown server type: {server_type}")
                    continue

                # record it
                self.clients[server_name] = {
                    "client": client,
                    "type": server_type,
                    "config": conf
                }

                # register that client's tools
                await self._register_tools_from_server(server_name, client, server_type)
                logger.info(f"Connected to {server_type} server: {server_name}")

            except Exception as e:
                logger.error(f"Failed to connect to server {server_name}: {e}")
                continue
    
    async def _register_tools_from_server(self, server_name: str, client: Any, transport: str):
        """Register tools from a specific server."""

        try:
            session = client.session
            if not session:
                logger.error(f"No valid session for server {server_name}")
                return
            
            tools_response = await session.list_tools()
            
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
            logger.error(f"Failed to register tools from {server_name}: {e}")
    
    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        logger.info("Disconnecting from all MCP servers...")
        
        for server_name, server_info in self.clients.items():
            try:
                await server_info["client"].disconnect()
                logger.info(f"Disconnected from {server_name}")
            except Exception as e:
                logger.error(f"Error disconnecting from {server_name}: {e}")
        
        self.clients.clear()
        self.tools_registry.clear()
    
    async def reconnect_server(self, server_name: str):
        """Reconnect to a specific server if connection is lost."""
        if server_name not in self.clients:
            logger.error(f"Server {server_name} not found in clients")
            return False
            
        server_info = self.clients[server_name]
        config = server_info["config"]
        
        try:
            # Disconnect existing connection
            await server_info["client"].disconnect()
            
            # Create new client and reconnect
            if config["type"] == "http":
                client = MCPHttpClient()
                await client.connect(config["url"])
            elif config["type"] == "stdio":
                client = MCPStdioClient()
                await client.connect(config["params"])
            
            # Update client reference
            self.clients[server_name]["client"] = client
            
            # Re-register tools
            await self._register_tools_from_server(server_name, client, config["type"])
            
            logger.info(f"Reconnected to {server_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reconnect to {server_name}: {e}")
            return False
    
    async def process_query(self, prompt: str, websocket=None, summary: bool = True, trace: bool = True):
        logger.info(f"[STEP 1] Starting process_query with prompt: {prompt}")
        query_trace: dict[str, str | None] = {"prompt": prompt, 
                                              "avaibale_tools": None, 
                                              "selected_tool": None, 
                                              "response_tool": None,
                                              "observation": None}
        
        if not self.tools_registry:
            logger.error("No tools available")
            raise RuntimeError("No MCP tools available. Call init() first.")

        try:
            # Build tools metadata from registry
            tools_meta = [
                {"name": tool["name"], "description": tool["description"], "schema": tool["schema"]}
                for tool in self.tools_registry
            ]

            if trace:
                query_trace["avaibale_tools"] = str(tools_meta)

            logger.info(f"[STEP 2] Using {len(tools_meta)} available tools")
            if websocket:
                await websocket.send_text("Selecting Tool...")


            # Build system prompt
            tool_docs = "\n\n".join(
                f"{tool['name']}: {tool['description']}\nInput schema: {tool['schema']}"
                for tool in tools_meta
            )

            system_prompt = (
                "You are a helpful assistant. "
                "You can call one of these tools by returning JSON exactly in the form:\n"
                '{ "call_function": "<tool_name>", "arguments": { … } }\n\n'
                "Available tools:\n" + tool_docs
            )

            # Get LLM response
            logger.info("[STEP 3] Calling LLM for tool selection...")
            llm_resp = await asyncio.to_thread(
                self.llm.call,
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=True
            )

            if trace:
                query_trace["selected_tool"] = llm_resp

            # Parse LLM response
            try:
                payload = json.loads(llm_resp)
                fn_name = payload["call_function"]
                fn_args = payload.get("arguments", {})
                logger.info(f"[STEP 4] Parsed function call: {fn_name} with args: {fn_args}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse LLM response: {e}")
                return llm_resp

            # Find the tool in registry
            tool_info = next((tool for tool in self.tools_registry if tool["name"] == fn_name), None)
            if not tool_info:
                return f"Tool '{fn_name}' not found in registry"

            # Execute tool using the appropriate session
            logger.info(f"[STEP 5] Executing tool {fn_name} on server {tool_info['server_id']}")
            try:
                tool_result = await tool_info["session"].call_tool(fn_name, fn_args)
                
                # Extract content
                if hasattr(tool_result, 'content'):
                    if isinstance(tool_result.content, list) and len(tool_result.content) > 0:
                        first_content = tool_result.content[0]
                        result_content = first_content.text if hasattr(first_content, 'text') else str(first_content)
                    else:
                        result_content = str(tool_result.content)
                else:
                    result_content = str(tool_result)
                
                result_content = result_content
                logger.info(f"[STEP 6] Tool result: {result_content}")
                # time.sleep(0.5)
                if websocket:
                    await websocket.send_text("Tool execution completed.")
                
            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                # Try to reconnect and retry once
                if await self.reconnect_server(tool_info['server_id']):
                    logger.info("Retrying after reconnection...")
                    # Update tool_info with new session
                    tool_info = next((tool for tool in self.tools_registry if tool["name"] == fn_name), None)
                    if tool_info:
                        tool_result = await tool_info["session"].call_tool(fn_name, fn_args)
                        result_content = str(tool_result)
                    else:
                        return f"Tool execution failed and reconnection didn't restore tool: {str(e)}"
                else:
                    return f"Tool execution failed: {str(e)}"
                
            if trace:
                query_trace["response_tool"] = str(tool_result)

            if not summary:
                return result_content
            
            if websocket:
                await websocket.send_text("Summarising Response...")

            # Get summary
            summary_prompt = (
                f"Original query: {prompt}\n"
                f"Tool `{fn_name}` returned: {result_content}\n\n"
                "Please summarise the outcome in plain text."
            )
            
            final = await asyncio.to_thread(
                self.llm.call,
                prompt=summary_prompt,
                system_prompt="",
                json_mode=False
            )

            if trace:
                query_trace["observation"] = final
                return final, query_trace
            
            return final, None
                
        except Exception as e:
            logger.error(f"Unexpected error in process_query: {e}", exc_info=True)
            if websocket:
                await websocket.send_text("An error occurred while processing your request: " + str(e))
            return f"An error occurred while processing your request: {str(e)}"

    def get_available_tools(self) -> List[str]:
        """Get list of all available tool names."""
        return [tool["name"] for tool in self.tools_registry]
    
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
        """Get tools registry in JSON-serializable format"""
        tools_json = []
        for tool in self.tools_registry:
            # Extract only JSON-serializable fields
            tool_data = {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "schema": tool.get("schema", {}),
                "server_id": tool.get("server_id", ""),
                "transport": tool.get("transport", "")
            }
            tools_json.append(tool_data)
        return tools_json

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