"""
AlphaVantage MCP Adapter
Integrates AlphaVantage client with validation and guidance.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, Tuple

from Tools.old_tools.mcp_alpha_vantage_client import AlphaVantageClient
from Agent.Adapters.Outbound.alphavantage_guidance import (
    AlphaVantageValidator,
    get_alphavantage_system_prompt_enhancement
)

logger = logging.getLogger(__name__)


class AlphaVantageAdapter:
    """
    Adapter for AlphaVantage API with integrated validation and guidance.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize adapter.

        Args:
            api_key: Optional API key override (defaults to ALPHAVANTAGE_API_KEY env var)
        """
        self.api_key = api_key
        self.client: Optional[AlphaVantageClient] = None
        self.validator = AlphaVantageValidator()

    async def __aenter__(self):
        """Initialize client."""
        self.client = AlphaVantageClient(api_key=self.api_key)
        await self.client.__aenter__()
        logger.info("AlphaVantage adapter initialized")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup client."""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
            logger.info("AlphaVantage adapter closed")

    async def list_tools(self):
        """Get list of available tools."""
        if not self.client:
            raise RuntimeError("Adapter not initialized. Use 'async with' context.")
        return await self.client.list_tools()

    async def call_tool(
            self,
            tool_name: str,
            arguments: Dict[str, Any]
    ) -> Tuple[bool, Any, Optional[str]]:
        """
        Call a tool with validation and error handling.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tuple of (success, result, error_message_or_guidance)
        """
        if not self.client:
            raise RuntimeError("Adapter not initialized. Use 'async with' context.")

        logger.info(f"Calling {tool_name} with arguments: {arguments}")

        # Step 1: Validate arguments
        is_valid, corrected_args, validation_error = self.validator.validate_tool_call(
            tool_name, arguments
        )

        if not is_valid:
            logger.error(f"Validation failed for {tool_name}: {validation_error}")
            return False, None, validation_error

        if corrected_args != arguments:
            logger.info(f"Arguments corrected: {arguments} -> {corrected_args}")

        try:
            # Step 2: Execute the tool
            result = await self.client.call_tool(tool_name, corrected_args)

            # Step 3: Check for API errors
            error_type = self.validator.detect_error_in_response(str(result))

            if error_type:
                guidance = self.validator.get_error_guidance(
                    tool_name, error_type, corrected_args
                )
                logger.warning(f"API error in {tool_name}: {error_type}")
                return False, result, guidance

            logger.info(f"Successfully executed {tool_name}")
            return True, result, None

        except Exception as e:
            error_msg = f"Exception in {tool_name}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg

    async def call_tool_with_retry(
            self,
            tool_name: str,
            arguments: Dict[str, Any],
            max_retries: int = 3,
            base_delay: float = 2.0
    ) -> Tuple[bool, Any, Optional[str]]:
        """
        Call a tool with automatic retry on rate limit errors.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            max_retries: Maximum number of retries
            base_delay: Base delay between retries (exponential backoff)

        Returns:
            Tuple of (success, result, error_message_or_guidance)
        """
        for attempt in range(max_retries):
            logger.debug(f"Attempt {attempt + 1}/{max_retries} for {tool_name}")

            success, result, error = await self.call_tool(tool_name, arguments)

            if success:
                return success, result, error

            # Check if it's a rate limit error and retry if so
            if error and "rate limit" in error.lower():
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Rate limit hit. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

            # For other errors, don't retry
            return False, result, error

        return False, None, "Max retries exceeded"

    def get_system_prompt_enhancement(self) -> str:
        """
        Get system prompt enhancement for LLM.
        Contains critical rules for using AlphaVantage tools correctly.
        """
        return get_alphavantage_system_prompt_enhancement()