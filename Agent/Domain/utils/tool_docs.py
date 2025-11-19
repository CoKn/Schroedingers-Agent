# Agent/Domain/utils/tool_docs.py
from typing import Iterable, Mapping, Callable


def format_tool_docs(tools_meta: Iterable[Mapping]) -> str:
    return "\n\n".join(
        f"{t['name']}: {t.get('description', '')}\nInput schema: {t.get('schema', {})}"
        for t in tools_meta
    )


def format_single_tool_doc(tool: Mapping) -> str:
    return (
        f"{tool['name']}: {tool.get('description', '')}\n"
        f"Input schema: {tool.get('schema', {})}"
    )


def make_get_tool_docs(mcp) -> Callable[[str | None], str]:
    """
    Factory that builds a get_tool_docs(tool_name) callable for LLMPlanner.

    - If tool_name is None  -> returns docs for all tools.
    - If tool_name is given -> returns docs for that single tool.
    - Uses a simple in-memory cache of tools_meta fetched from MCP.
    """
    tools_meta_cache: list[Mapping] | None = None

    def _ensure_tools_meta() -> list[Mapping]:
        nonlocal tools_meta_cache
        if tools_meta_cache is None:
            tools_meta_cache = mcp.get_tools_json()
        return tools_meta_cache

    def get_tool_docs(tool_name: str | None = None) -> str:
        tools_meta = _ensure_tools_meta()

        if tool_name:
            for t in tools_meta:
                if t["name"] == tool_name:
                    return format_single_tool_doc(t)
            raise ValueError(f"Tool '{tool_name}' not found in available tools")

        # All tools
        return format_tool_docs(tools_meta)

    return get_tool_docs
