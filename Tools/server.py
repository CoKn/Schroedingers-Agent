from fastmcp import FastMCP
import re
import math
import datetime
from typing import List, Dict, Optional

# Persistent session HTTP server for streamable-http transport
mcp = FastMCP(
    name="Marketing Tools",
    json_response=True
)


# --- Utilities ---
def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return text


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def _count_syllables(word: str) -> int:
    w = word.lower()
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_is_vowel = False
    for ch in w:
        is_vowel = ch in vowels
        if is_vowel and not prev_is_vowel:
            count += 1
        prev_is_vowel = is_vowel
    if w.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def _flesch_reading_ease(text: str) -> float:
    words = _words(text)
    sents = _sentences(text)
    if not words or not sents:
        return 0.0
    syllables = sum(_count_syllables(w) for w in words)
    wps = len(words) / max(len(sents), 1)
    spw = syllables / max(len(words), 1)
    return 206.835 - 1.015 * wps - 84.6 * spw


def _keyword_stats(text: str, keywords: List[str]) -> Dict[str, Dict[str, float | int | bool]]:
    text_l = text.lower()
    total_words = len(_words(text))
    stats: Dict[str, Dict[str, float | int | bool]] = {}
    for kw in keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        count = len(re.findall(rf"\b{re.escape(kw_l)}\b", text_l))
        density = (count / total_words * 100.0) if total_words else 0.0
        stats[kw] = {
            "present": count > 0,
            "count": count,
            "density_pct": round(density, 2),
        }
    return stats


# --- Content Creation Pipeline Tools ---
@mcp.tool()
def ideate_topics(
    product: str,
    audience: str,
    pains: List[str],
    pillars: Optional[List[str]] = None,
    count: int = 12,
) -> Dict[str, List[str]]:
    """Generate topic ideas from product, audience, pains, and optional content pillars."""
    pillars = pillars or ["education", "use-cases", "comparisons", "case-studies", "trends"]
    ideas: List[str] = []
    for i, pain in enumerate(pains):
        for p in pillars:
            ideas.append(f"{pain.title()} — {product} for {audience} ({p})")
            if len(ideas) >= count:
                break
        if len(ideas) >= count:
            break
    while len(ideas) < count:
        ideas.append(f"{product} for {audience}: guide {len(ideas)+1}")
    return {"topics": ideas[:count]}


@mcp.tool()
def keyword_expand(primary: str, locale: str = "en", max_items: int = 20) -> Dict[str, List[str]]:
    """Expand a primary keyword into variants using common intent modifiers (no external calls)."""
    modifiers = [
        "best", "vs", "how to", "guide", "template", "checklist", "examples",
        "pricing", "alternatives", "review", "for beginners", "for {aud}", "2025",
        "setup", "integration", "metrics", "roi", "tutorial", "compare", "tools"
    ]
    variants: List[str] = []
    for m in modifiers:
        variants.append(f"{primary} {m}")
        if len(variants) >= max_items:
            break
    return {"primary": primary, "variants": variants}


@mcp.tool()
def outline_from_topic(
    topic: str,
    target_keywords: Optional[List[str]] = None,
    include_faq: bool = True,
) -> Dict[str, object]:
    """Create a structured outline with H2/H3 sections and FAQ based on a topic and keywords."""
    target_keywords = target_keywords or []
    h2 = [
        "Overview",
        "Why it matters",
        "Step-by-step",
        "Common mistakes",
        "Examples",
        "Tools & resources",
    ]
    h3 = {
        "Step-by-step": ["Step 1", "Step 2", "Step 3"],
        "Common mistakes": ["Pitfall 1", "Pitfall 2"],
    }
    faq = [f"What is {topic}?", f"How to start with {topic}?", f"Best tools for {topic}?"] if include_faq else []
    return {
        "title_suggestions": [f"{topic}: A Practical Guide", f"{topic} — Step-by-Step"],
        "h2": h2,
        "h3": h3,
        "faq": faq,
        "target_keywords": target_keywords,
    }


@mcp.tool()
def brief_from_outline(
    topic: str,
    audience: str,
    funnel_stage: str,
    target_keywords: List[str],
    tone: str = "practical",
    reading_level: str = "8th",
) -> Dict[str, object]:
    """Create a content brief specifying audience, promise, structure, keywords, internal links, and CTA."""
    primary_kw = target_keywords[0] if target_keywords else _slugify(topic).replace("-", " ")
    return {
        "topic": topic,
        "audience": audience,
        "promise": f"Help {audience} achieve outcomes with {topic}.",
        "tone": tone,
        "reading_level": reading_level,
        "funnel_stage": funnel_stage,
        "primary_keyword": primary_kw,
        "secondary_keywords": target_keywords[1:5],
        "sections": [
            {"h2": "Overview", "bullets": ["Definition", "Who it's for", "When to use"]},
            {"h2": "Step-by-step", "bullets": ["Step 1", "Step 2", "Step 3"]},
            {"h2": "Examples", "bullets": ["Example 1", "Example 2"]},
            {"h2": "Common mistakes", "bullets": ["Mistake 1", "Mistake 2"]},
            {"h2": "Tools & resources", "bullets": ["Tool 1", "Tool 2"]},
        ],
        "internal_links": ["/blog/related-1", "/blog/related-2"],
        "external_sources": ["https://example.com/credible-source"],
        "cta": {
            "text": "Start free trial",
            "url": "/signup",
            "placement": ["after Overview", "end of post"],
        },
    }


@mcp.tool()
def title_variants(base: str, style: str = "benefit", count: int = 10) -> Dict[str, List[str]]:
    """Generate headline variations using common copy patterns (no external calls)."""
    patterns = [
        "How to {b}",
        "{b}: The Complete Guide",
        "{n} Proven Ways to {b}",
        "{b} (Without the Headache)",
        "Stop Wasting Time: {b}",
        "{b} — Checklist",
        "{b} vs Alternatives: What to Choose",
        "Beginner to Pro: {b}",
        "{b} in 30 Minutes",
        "{b} for 2025",
    ]
    out: List[str] = []
    for i, p in enumerate(patterns):
        title = p.format(b=base, n=7 + (i % 5))
        out.append(title)
        if len(out) >= count:
            break
    return {"titles": out}


@mcp.tool()
def meta_description(
    title: str,
    angle: str,
    target_keywords: Optional[List[str]] = None,
    max_len: int = 155,
) -> Dict[str, str | int]:
    """Create a meta description including primary keyword and benefit, trimmed to length."""
    target_keywords = target_keywords or []
    primary = target_keywords[0] if target_keywords else ""
    desc = f"{title} — {angle}. Learn {primary or 'practical steps'} with examples and templates."
    return {"description": (desc[: max_len]).rstrip(), "length": len((desc[: max_len]).rstrip())}


@mcp.tool()
def draft_skeleton(
    outline: Dict[str, object],
    word_count: int = 1200,
) -> Dict[str, str | int]:
    """Produce a Markdown skeleton for the article body based on the outline/brief."""
    sections = []
    title = (outline.get("title_suggestions") or ["Untitled"]) [0]
    sections.append(f"# {title}\n")
    for h2 in outline.get("h2", []):
        sections.append(f"\n## {h2}\n")
        for h3 in (outline.get("h3", {}) or {}).get(h2, []):
            sections.append(f"\n### {h3}\n")
            sections.append("<write 1–2 paragraphs>\n")
    for q in outline.get("faq", []):
        sections.append(f"\n## FAQ: {q}\n")
        sections.append("<answer in 3–5 sentences>\n")
    body = "".join(sections)
    return {"approx_words": word_count, "markdown": body}


@mcp.tool()
def seo_analyze(
    text: str,
    target_keywords: Optional[List[str]] = None,
    title: Optional[str] = None,
    meta: Optional[str] = None,
) -> Dict[str, object]:
    """Analyze readability, keyword coverage/density, and basic SEO heuristics."""
    target_keywords = target_keywords or []
    wc = len(_words(text))
    fre = round(_flesch_reading_ease(text), 2)
    kw_stats = _keyword_stats(text, target_keywords)
    title_len = len(title) if title else 0
    meta_len = len(meta) if meta else 0
    suggestions: List[str] = []
    if fre < 55:
        suggestions.append("Improve readability: use shorter sentences and simpler words.")
    for kw, st in kw_stats.items():
        if not st["present"]:
            suggestions.append(f"Add target keyword: '{kw}'.")
        elif st["density_pct"] < 0.3:
            suggestions.append(f"Increase usage of '{kw}' to ~0.5–1.5%.")
    if title and not target_keywords or (title and target_keywords and target_keywords[0].lower() not in title.lower()):
        suggestions.append("Include the primary keyword in the H1.")
    if meta and meta_len < 120:
        suggestions.append("Extend meta description to ~150–160 characters.")
    if meta and target_keywords and target_keywords[0].lower() not in meta.lower():
        suggestions.append("Include the primary keyword in meta description.")
    return {
        "word_count": wc,
        "flesch_reading_ease": fre,
        "keyword_stats": kw_stats,
        "title_length": title_len,
        "meta_length": meta_len,
        "suggestions": suggestions,
    }


@mcp.tool()
def distribution_checklist(
    channels: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Return a distribution checklist for common channels with UTM reminder."""
    channels = channels or ["LinkedIn", "X", "Reddit", "Hacker News", "Newsletter"]
    base = [
        "Create 3–5 post variants",
        "Add UTM params",
        "Schedule posts",
        "Reply to comments for 48h",
        "Repurpose into short video",
    ]
    return {"channels": channels, "checklist": base}


@mcp.tool()
def finalize_markdown(
    title: str,
    description: str,
    tags: List[str],
    body_markdown: str,
    slug: Optional[str] = None,
) -> Dict[str, str]:
    """Combine front matter and body into a publish-ready Markdown document."""
    slug = slug or _slugify(title)
    fm = [
        "---",
        f"title: {title}",
        f"description: {description}",
        f"date: {datetime.date.today().isoformat()}",
        f"slug: {slug}",
        f"tags: [{', '.join(tags)}]",
        "---\n\n",
    ]
    doc = "\n".join(fm) + body_markdown.strip() + "\n"
    return {"slug": slug, "markdown": doc}


# Simple utility/demo tools retained
@mcp.tool()
def sum(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8081)