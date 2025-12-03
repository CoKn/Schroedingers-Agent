from fastmcp import FastMCP
from pathlib import Path
import tempfile
import subprocess
import shutil
import os
import re


mcp = FastMCP(
    name="Local LaTeX Builder",
    json_response=True
)

# Project root = directory where this Python file lives
PROJECT_ROOT = Path(__file__).resolve().parent

# Save all generated PDFs here
REPORTS_DIR = PROJECT_ROOT / "Tools" / "reports"


def _check_engine() -> None:
    """
    Ensure pdflatex exists.
    """
    if shutil.which("pdflatex") is None:
        raise RuntimeError(
            "pdflatex not found. Install TeX Live inside your WSL Ubuntu:\n"
            "    sudo apt install texlive-latex-base"
        )


def _sanitize_filename(name: str) -> str:
    """
    Convert company name into a filesystem-safe filename.
    """
    name = name.strip().lower()
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-z0-9_\-]", "", name)
    return name or "report"


@mcp.tool()
def compile_latex(source: str, company_name: str) -> dict:
    """
    Compile a LaTeX document into a PDF using the local pdflatex engine.

    The final PDF will be saved into:
        Tools/reports/<company_name>_report.pdf

    PARAMETERS
    ----------
    source : str
        Complete LaTeX document.
    company_name : str
        Company name used to generate the PDF filename.

    RETURNS
    -------
    {
        "success": bool,
        "pdf_path": str | None,
        "workdir": str,
        "log": str
    }
    """

    _check_engine()

    # Create output directory if missing
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Convert company name into a filename
    safe_name = _sanitize_filename(company_name)
    final_pdf_path = REPORTS_DIR / f"{safe_name}_report.pdf"

    # Temporary working directory
    workdir = Path(tempfile.mkdtemp(prefix="latex_mcp_"))
    tex_file = workdir / "document.tex"
    pdf_tmp = workdir / "document.pdf"

    # Write source LaTeX
    tex_file.write_text(source, encoding="utf-8")

    # Run LaTeX twice
    cmd = ["pdflatex", "-interaction=nonstopmode", tex_file.name]

    p1 = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    p2 = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)

    log = (
        "=== FIRST RUN ===\n" + p1.stdout + p1.stderr +
        "\n\n=== SECOND RUN ===\n" + p2.stdout + p2.stderr
    )

    if not pdf_tmp.exists():
        return {
            "success": False,
            "pdf_path": None,
            "workdir": str(workdir.resolve()),
            "log": log
        }

    # Move final PDF into Tools/reports
    shutil.copy2(pdf_tmp, final_pdf_path)

    return {
        "success": True,
        "pdf_path": str(final_pdf_path.resolve()),
        "workdir": str(workdir.resolve()),
        "log": log
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8086)
