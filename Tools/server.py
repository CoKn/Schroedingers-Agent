from fastmcp import FastMCP

# Persistent session HTTP server for streamable-http transport
mcp = FastMCP(
    name="Math tools",
    json_response=True
)

@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.tool()
def scrape(): 
    """Scrape a webpate"""
    return

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)