from fastmcp import FastMCP
from typing import List
from bs4.element import AttributeValueList
import requests
from ddgs import DDGS
from html_to_markdown import convert_to_markdown
from bs4 import BeautifulSoup

# MCP server
mcp = FastMCP(
    name="Websearch and scraping",
    json_response=True
)

# MCP Tools
@mcp.tool()
def duckduckgo_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Search DuckDuckGo and return structured results.

    Args:
        query: The search term.
        max_results: Maximum number of results to return.

    Returns:
        A list of result objects with keys: title, href, body.
        This is a real JSON array (not a string), suitable for schema validation.
    """
    results: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            results.append({
                "title": item.get("title", ""),
                "href": item.get("href", ""),
                "body": item.get("body", ""),
            })
    return results

@mcp.tool()
def get_website_urls(url: str) -> List[str | AttributeValueList | None]:
    """Extracts all hyperlinks from a webpage.

        This function fetches a webpage from the provided URL, parses the HTML content,
        and extracts all hyperlinks (anchor tags) found on the page. It processes relative
        URLs to convert them to absolute URLs by prepending the base URL.

        Args:
            url: The complete URL of the webpage to fetch (e.g., 'https://example.com')

        Returns:
            A list of URLs extracted from the webpage. Each element can be a string URL,
            a BeautifulSoup AttributeValueList, or None if the href attribute is missing.

        Raises:
            requests.RequestException: If the HTTP request fails
    """
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    all_anchors = soup.find_all("a")
    urls = []
    for anchor in all_anchors:
        if anchor.get("href", "") == "#":
            continue

        elif anchor.get("href", "").startswith('/'):
            if url.endswith('/'):
                urls.append(url[:-1] + anchor.get("href"))
            else:
                urls.append(url + anchor.get("href"))
        else:
            urls.append(anchor.get("href"))
    return urls[:5]


@mcp.tool()
def get_website_content(url: str) -> str:
    """Fetches a webpage and converts it to clean markdown text.

    This function retrieves HTML content from the specified URL, removes images
    and SVG elements, then converts the cleaned HTML to markdown format.

    Args:
        url: The complete URL of the webpage to fetch

    Returns:
        A string containing the markdown representation of the webpage with
        images and SVG elements removed.

    Raises:
        requests.RequestException: If the HTTP request fails
    """
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')

    # Remove every <img> tag entirely
    for img_tag in soup.find_all('img'):
        img_tag.decompose()

    # Remove every <svg> tag entirely
    for svg_tag in soup.find_all('svg'):
        svg_tag.decompose()

    # Remove any <a> that wraps only an <img> or <svg> (so no “image links” remain)
    for a_tag in soup.find_all('a'):
        if a_tag.find('img') or a_tag.find('svg'):
            a_tag.decompose()


    return convert_to_markdown(str(soup))[:500]


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8082)
