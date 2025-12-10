from fastmcp import FastMCP
from pathlib import Path
import tempfile
import subprocess
import shutil
import re


mcp = FastMCP(
    name="Local LaTeX Builder",
    json_response=True
)

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "reports"


# =====================================================================
# UTILITIES
# =====================================================================

# Characters that commonly break LaTeX when coming from raw text.
# NOTE: We deliberately do NOT escape backslash, so that the agent can
# still inject intentional LaTeX (e.g., math, lists) when desired.
LATEX_SPECIAL_CHARS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\^{}",
}


def escape_latex(text: str) -> str:
    """
    Escape LaTeX-special characters in plain narrative text.

    This is meant for sections that are mostly prose. It leaves backslashes
    alone so that the agent may still intentionally add LaTeX commands
    (e.g., \\textbf, math environments) when needed.
    """
    if not isinstance(text, str):
        return ""
    return "".join(LATEX_SPECIAL_CHARS.get(ch, ch) for ch in text)


def _check_engine() -> None:
    """
    Ensure pdflatex exists on the system PATH.
    """
    if shutil.which("pdflatex") is None:
        raise RuntimeError(
            "pdflatex not found. Install TeX Live in your environment, e.g.:\n"
            "    sudo apt install texlive-full"
        )


def _sanitize_filename(name: str) -> str:
    """
    Convert company name into a filesystem-safe filename.
    """
    name = (name or "").strip().lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_\-]", "", name) or "report"


# -------------------------------------------------------------------------
# Placeholder detection helpers
# -------------------------------------------------------------------------
PLACEHOLDER_PATTERNS = [
    "complete latex document string",
    "latex document source",
    "<latex>",
    "<report>",
    "insert here",
    "placeholder",
    "dummy",
    "example content",
    "todo",
]


def _contains_placeholder(text: str) -> bool:
    """
    Heuristic detection of obviously placeholder-y LaTeX sources.
    """
    text_low = (text or "").lower()
    return any(pattern in text_low for pattern in PLACEHOLDER_PATTERNS)


def _is_valid_latex(text: str) -> bool:
    """
    Minimal check for 'complete' LaTeX document structure.
    """
    if not isinstance(text, str):
        return False
    return (
        "\\documentclass" in text
        and "\\begin{document}" in text
        and "\\end{document}" in text
    )


# =====================================================================
# ROBUST LATEX TEMPLATE WITH TABLES, HEADERS, APPENDIX, ETC.
# =====================================================================

INVESTMENT_REPORT_TEMPLATE = r"""
\documentclass[12pt]{article}

\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{tabularx}
\usepackage{float}
\usepackage{geometry}
\usepackage{pgfplots}
\usepackage{hyperref}
\usepackage{fancyhdr}
\usepackage{xcolor}
\usepackage{siunitx}
\usepackage{titlesec}
\usepackage{setspace}

\geometry{margin=1in}
\pgfplotsset{compat=1.18}
\hypersetup{colorlinks=true, linkcolor=blue}

\setlength{\parskip}{6pt}
\setlength{\parindent}{0pt}
\onehalfspacing

\pagestyle{fancy}
\fancyhf{}
\lhead{Investment Report --- %(company_name)s}
\rhead{\thepage}

\title{\textbf{Investment Evaluation Report: %(company_name)s}}
\author{Autonomous MCP Agent}
\date{\today}

\begin{document}
\maketitle
\tableofcontents
\newpage

%% ================================
%% MAIN SECTIONS
%% ================================

\section{Executive Summary}
%(executive_summary)s

\section{Valuation}
%(valuation)s

\section{Financial Health}
%(financial_health)s

\section{Growth Outlook}
%(growth)s

\section{Corporate Strategy}
%(strategy)s

\section{Insider Trading}
%(insider_trading)s

\section{News \& Market Sentiment}
%(news)s

\section{Risk Assessment}
%(risks)s

\section{Conclusions}
%(conclusions)s

%% ================================
%% OPTIONAL APPENDIX
%% ================================
%(appendix)s

\end{document}
"""


# =====================================================================
# TOOL 1: build_investment_report_latex
# =====================================================================
@mcp.tool()
def build_investment_report_latex(
    company_name: str,
    executive_summary: str,
    valuation: str,
    financial_health: str,
    growth: str,
    strategy: str,
    insider_trading: str,
    news: str,
    risks: str,
    conclusions: str,
    appendix: str = "",
) -> dict:
    """
    Assemble a complete LaTeX investment report from prepared section texts.

    PURPOSE
    -------
    This tool does NOT fetch data on its own. Instead, it expects that the
    agent has already:
      - called the valuation, financial, SEC, insider, and news tools,
      - reviewed its own reasoning trace,
      - optionally used a summarisation tool to turn raw outputs into
        narrative text for each section.

    The tool then:
      - escapes LaTeX-special characters in each narrative section,
      - injects them into a fixed LaTeX template,
      - returns a single LaTeX document string ready for compilation.

    NOTE ON APPENDIX
    ----------------
    - `appendix` is inserted *as-is* (no escaping). Use this for raw LaTeX
      tables, charts, or any advanced formatting the agent wants to control.

    OUTPUT FORMAT (JSON)
    --------------------
    {
      "company_name": "<str>",
      "latex_source": "<full LaTeX document string>",
      "missing_or_empty_sections": ["<section_name>", ...],
      "ready_for_compilation": <bool>
    }
    """

    # Escape narrative sections; appendix is left raw so it can contain LaTeX.
    sections = {
        "executive_summary": escape_latex(executive_summary or ""),
        "valuation": escape_latex(valuation or ""),
        "financial_health": escape_latex(financial_health or ""),
        "growth": escape_latex(growth or ""),
        "strategy": escape_latex(strategy or ""),
        "insider_trading": escape_latex(insider_trading or ""),
        "news": escape_latex(news or ""),
        "risks": escape_latex(risks or ""),
        "conclusions": escape_latex(conclusions or ""),
        "appendix": appendix or "",  # raw LaTeX allowed
    }

    # Basic completeness check
    missing_or_empty = [
        name for name, text in sections.items()
        if name != "appendix" and (not text or text.strip() == "")
    ]

    latex_source = INVESTMENT_REPORT_TEMPLATE % {
        "company_name": escape_latex(company_name or ""),
        **sections,
    }

    return {
        "company_name": company_name,
        "latex_source": latex_source,
        "missing_or_empty_sections": missing_or_empty,
        "ready_for_compilation": len(missing_or_empty) == 0,
    }


# =====================================================================
# TOOL 2: compile_latex
# =====================================================================
@mcp.tool()
def compile_latex(source: str, company_name: str) -> dict:
    """
    Compile a LaTeX document into a PDF using the local pdflatex engine.

    TYPICAL WORKFLOW
    ----------------
    1. Agent gathers data using upstream tools (valuation, health, SEC, etc.).
    2. Agent writes narrative text for each report section (possibly via
       a summarisation tool).
    3. Agent calls `build_investment_report_latex` to obtain a full LaTeX
       document in `latex_source`.
    4. Agent calls this tool with:
           source = <latex_source>
           company_name = "<company>"

    BEHAVIOR
    --------
    - Rejects missing / non-string / obviously placeholder or too-short input.
    - If `source` does not contain a \\documentclass / \\begin{document} /
      \\end{document}, it auto-wraps the body into a minimal article.
    - Runs pdflatex twice to get references / TOC consistent.

    RETURNS
    -------
    {
      "success": bool,
      "pdf_path": str | None,
      "workdir": str | None,
      "log": str
    }
    """

    # Basic type / null / length checks
    if source is None or not isinstance(source, str):
        return {
            "success": False,
            "pdf_path": None,
            "workdir": None,
            "log": (
                "LaTeX source was not provided or not a string. "
                "The agent must generate the full LaTeX report before "
                "calling compile_latex."
            ),
        }

    stripped = source.strip()
    if len(stripped) < 200:
        return {
            "success": False,
            "pdf_path": None,
            "workdir": None,
            "log": (
                "LaTeX document is too short. "
                "It likely does not contain a full report. "
                "Populate all main sections before compiling."
            ),
        }

    if _contains_placeholder(source):
        return {
            "success": False,
            "pdf_path": None,
            "workdir": None,
            "log": (
                "LaTeX source appears to contain placeholder text. "
                "Ensure the report sections are filled with actual analysis "
                "before calling compile_latex."
            ),
        }

    try:
        _check_engine()
    except Exception as e:
        return {
            "success": False,
            "pdf_path": None,
            "workdir": None,
            "log": f"pdflatex missing or misconfigured: {str(e)}",
        }

    # Auto-wrap if not a complete LaTeX document
    needs_wrapper = not _is_valid_latex(source)
    if needs_wrapper:
        source_to_compile = (
            "\\documentclass[12pt]{article}\n"
            "\\usepackage{geometry}\n"
            "\\geometry{margin=1in}\n"
            "\\begin{document}\n"
            + source +
            "\n\\end{document}\n"
        )
    else:
        source_to_compile = source

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = _sanitize_filename(company_name or "report")
    final_pdf_path = REPORTS_DIR / f"{safe_name}_report.pdf"

    workdir = Path(tempfile.mkdtemp(prefix="latex_mcp_"))
    tex_file = workdir / "document.tex"
    pdf_tmp = workdir / "document.pdf"

    tex_file.write_text(source_to_compile, encoding="utf-8")

    cmd = ["pdflatex", "-interaction=nonstopmode", tex_file.name]

    # Two passes for TOC/refs
    p1 = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    p2 = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)

    log = (
        ("Wrapper applied.\n\n" if needs_wrapper else "")
        + "=== FIRST RUN ===\n" + p1.stdout + p1.stderr
        + "\n\n=== SECOND RUN ===\n" + p2.stdout + p2.stderr
    )

    if not pdf_tmp.exists():
        return {
            "success": False,
            "pdf_path": None,
            "workdir": str(workdir.resolve()),
            "log": "LaTeX compilation failed.\n" + log,
        }

    shutil.copy2(pdf_tmp, final_pdf_path)

    return {
        "success": True,
        "pdf_path": str(final_pdf_path.resolve()),
        "workdir": str(workdir.resolve()),
        "log": log,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8086)
