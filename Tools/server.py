from fastmcp import FastMCP


# MCP server
mcp = FastMCP(
    name="Math",
    json_response=True
)

# MCP Tools
@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)
