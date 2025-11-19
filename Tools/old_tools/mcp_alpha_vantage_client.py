"""
General AlphaVantage MCP Client
Provides flexible access to all AlphaVantage API endpoints via MCP protocol.
"""
import asyncio
import os
from typing import Optional, Dict, Any, List
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class AlphaVantageClient:
    """
    General client for AlphaVantage API via MCP protocol.
    Supports all AlphaVantage endpoints dynamically.
    """

    DEFAULT_CATEGORIES = [
        "core_stock_apis",
        "alpha_intelligence",
        "fundamental_data",
        "forex",
        "economic_indicators",
        "ping"
    ]

    def __init__(self, api_key: Optional[str] = None, categories: Optional[List[str]] = None):
        """
        Initialize AlphaVantage client.

        Args:
            api_key: AlphaVantage API key. If None, loads from ALPHAVANTAGE_API_KEY env var.
            categories: List of API categories to enable. If None, uses all default categories.
        """
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "AlphaVantage API key not found. "
                "Set ALPHAVANTAGE_API_KEY in .env file or pass api_key parameter."
            )

        self.categories = categories or self.DEFAULT_CATEGORIES
        self.base_url = "https://mcp.alphavantage.co/mcp"
        self.session: Optional[ClientSession] = None

    def _build_url(self) -> str:
        """Build the MCP URL with API key and categories."""
        categories_str = ",".join(self.categories)
        return f"{self.base_url}?apikey={self.api_key}&categories={categories_str}"

    async def __aenter__(self):
        """Async context manager entry."""
        url = self._build_url()
        self._client_context = streamablehttp_client(url)
        read, write, _ = await self._client_context.__aenter__()

        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if hasattr(self, '_session_context'):
            await self._session_context.__aexit__(exc_type, exc_val, exc_tb)
        if hasattr(self, '_client_context'):
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)

    async def list_tools(self) -> List[str]:
        """
        Get list of available tools/endpoints.

        Returns:
            List of tool names
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        tools = (await self.session.list_tools()).tools
        return [tool.name for tool in tools]

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """
        Call any AlphaVantage tool/endpoint.

        Args:
            tool_name: Name of the tool (e.g., 'GLOBAL_QUOTE', 'NEWS_SENTIMENT')
            arguments: Dictionary of arguments for the tool

        Returns:
            Tool response content
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        arguments = arguments or {}
        result = await self.session.call_tool(tool_name, arguments)
        return result.content

    async def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Dictionary with tool schema and description
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        tools = (await self.session.list_tools()).tools
        for tool in tools:
            if tool.name == tool_name:
                return {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
        raise ValueError(f"Tool '{tool_name}' not found")


# Convenience functions for common operations
async def get_stock_quote(symbol: str, api_key: Optional[str] = None) -> Any:
    """Get current stock quote for a symbol."""
    async with AlphaVantageClient(api_key=api_key) as client:
        return await client.call_tool("GLOBAL_QUOTE", {"symbol": symbol})


async def search_symbol(keywords: str, api_key: Optional[str] = None) -> Any:
    """Search for stock symbols by company name or keywords."""
    async with AlphaVantageClient(api_key=api_key) as client:
        return await client.call_tool("SYMBOL_SEARCH", {"keywords": keywords})


async def get_news_sentiment(
    tickers: Optional[str] = None,
    topics: Optional[str] = None,
    limit: int = 50,
    api_key: Optional[str] = None
) -> Any:
    """
    Get news sentiment analysis.

    Args:
        tickers: Ticker symbol(s), comma-separated (e.g., 'AAPL' or 'AAPL,MSFT')
        topics: Topics to filter (e.g., 'technology', 'earnings')
        limit: Number of results (default: 50, max: 1000)
        api_key: Optional API key override
    """
    args = {"limit": limit}
    if tickers:
        args["tickers"] = tickers
    if topics:
        args["topics"] = topics

    async with AlphaVantageClient(api_key=api_key) as client:
        return await client.call_tool("NEWS_SENTIMENT", args)


async def get_currency_exchange_rate(
    from_currency: str,
    to_currency: str,
    api_key: Optional[str] = None
) -> Any:
    """Get real-time currency exchange rate."""
    async with AlphaVantageClient(api_key=api_key) as client:
        return await client.call_tool(
            "CURRENCY_EXCHANGE_RATE",
            {"from_currency": from_currency, "to_currency": to_currency}
        )


async def get_company_overview(symbol: str, api_key: Optional[str] = None) -> Any:
    """Get comprehensive company overview and fundamentals."""
    async with AlphaVantageClient(api_key=api_key) as client:
        return await client.call_tool("OVERVIEW", {"symbol": symbol})