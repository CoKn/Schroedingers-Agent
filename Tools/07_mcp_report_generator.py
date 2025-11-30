from fastmcp import FastMCP
from typing import List, Dict, Optional
import base64
import textwrap
import urllib.parse

mcp = FastMCP(
    name="Overleaf LaTeX Report Generator",
    json_response=True
)

# -------------------------------------------------------------
# Build a structured LaTeX document
# -------------------------------------------------------------
def escape_latex(s: str) -> str:
    replacements = {
        "\\": r"\\",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s


def build_latex_document(
    title: str,
    author: Optional[str],
    sections: List[Dict]
) -> str:

    preamble = textwrap.dedent("""
    \\documentclass{article}
    \\usepackage[utf8]{inputenc}
    \\usepackage{lmodern}
    \\usepackage{hyperref}
    \\usepackage{amsmath, amssymb}
    \\usepackage{geometry}
    \\geometry{margin=1in}
    """)

    header = (
        "\\title{" + escape_latex(title) + "}\n"
        "\\author{" + escape_latex(author or "") + "}\n"
        "\\date{\\today}\n\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\tableofcontents\n"
        "\\newpage\n"
    )

    body = []
    for sec in sections:
        heading = escape_latex(sec.get("heading", ""))
        content = sec.get("content", "")
        level = sec.get("level", 1)

        if level == 1:
            cmd = "section"
        elif level == 2:
            cmd = "subsection"
        else:
            cmd = "subsubsection"

        body.append(f"\\{cmd}{{{heading}}}\n{content}\n")

    return preamble + "\n" + header + "\n".join(body) + "\n\\end{document}\n"


# -------------------------------------------------------------
# MCP TOOL: latex_generate_overleaf_link
# -------------------------------------------------------------
@mcp.tool()
def latex_generate_overleaf_link(
    title: str,
    author: Optional[str] = None,
    sections: List[Dict] = []
) -> Dict:
    """
    Generate a LaTeX report and return a URL that opens it in Overleaf.

    Overleaf will automatically create a new project containing the LaTeX
    source, using the 'snip_uri' base64 API.
    """

    # Build .tex file content
    latex_source = build_latex_document(title, author, sections)

    # Base64-encode for Overleaf
    encoded = base64.b64encode(latex_source.encode("utf-8")).decode("ascii")

    # Construct Overleaf URL
    data_url = f"data:application/x-tex;base64,{encoded}"
    encoded_param = urllib.parse.quote(data_url, safe="")

    overleaf_url = f"https://www.overleaf.com/docs?snip_uri={encoded_param}"

    return {
        "overleaf_url": overleaf_url,
        "latex_source": latex_source
    }


# -------------------------------------------------------------
# MCP TOOL: latex_raw_overleaf_link
# -------------------------------------------------------------
@mcp.tool()
def latex_raw_overleaf_link(
    latex_source: str
) -> Dict:
    """
    Takes raw LaTeX and returns a link that opens it in Overleaf.
    """

    encoded = base64.b64encode(latex_source.encode("utf-8")).decode("ascii")
    encoded_param = urllib.parse.quote(
        f"data:application/x-tex;base64,{encoded}", safe=""
    )

    return {
        "overleaf_url": f"https://www.overleaf.com/docs?snip_uri={encoded_param}"
    }


# -------------------------------------------------------------
# Run server
# -------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8087)