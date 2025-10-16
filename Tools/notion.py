from fastmcp import FastMCP


# MCP server
mcp = FastMCP(
    name="Notion",
    json_response=True
)




if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)