from __future__ import annotations
from typing import Any, Iterable
import json

Primitive = (str, int, float, bool, type(None))


def _escape_md(text: str) -> str:
    """Escape markdown table separators in inline content."""
    return text.replace("|", "\\|")


def _stringify(value: Any, code_block_threshold: int = 200) -> str:
    """Render a primitive value as markdown-friendly text.

    - Wrap multi-line or long strings in fenced code blocks
    - Otherwise render small values in inline code ticks when appropriate
    """
    if value is None:
        return "`null`"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, (int, float)):
        return f"`{value}`"
    if isinstance(value, str):
        s = value
        # Avoid rendering massive blank code fences for whitespace-only strings
        if not s.strip():
            return "(empty)"
        if "\n" in s or len(s) > code_block_threshold:
            return f"```\n{s}\n```"
        # Escape simple pipes to preserve table structure if used inline
        return f"`{_escape_md(s)}`"
    # Fallback for non-primitive accidentally passed here
    return f"`{_escape_md(str(value))}`"


def _all_dicts(items: Iterable[Any]) -> bool:
    return all(isinstance(x, dict) for x in items)


def _all_primitives(items: Iterable[Any]) -> bool:
    return all(isinstance(x, Primitive) for x in items)


def _common_primitive_keys(rows: list[dict]) -> list[str]:
    """Keys present in all rows whose values are primitive."""
    if not rows:
        return []
    keys = set(rows[0].keys())
    for r in rows[1:]:
        keys &= set(r.keys())
        if not keys:
            return []
    # Keep only keys that are consistently primitive
    result: list[str] = []
    for k in keys:
        if all(isinstance(r.get(k), Primitive) for r in rows):
            result.append(k)
    return result


def _render_table(rows: list[dict], keys: list[str], max_rows: int = 50) -> list[str]:
    lines: list[str] = []
    if not keys:
        return lines
    # Header
    lines.append("| " + " | ".join(_escape_md(str(k)) for k in keys) + " |")
    lines.append("|" + "|".join([" --- "] * len(keys)) + "|")
    # Rows
    for r in rows[:max_rows]:
        vals = [
            _escape_md(str(r.get(k))) if isinstance(r.get(k), str) else str(r.get(k))
            for k in keys
        ]
        lines.append("| " + " | ".join(vals) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n… ({len(rows) - max_rows} more rows omitted)")
    return lines


def json_to_markdown(
    data: Any,
    *,
    title: str | None = None,
    heading_level: int = 2,
    sort_keys: bool = False,
    max_string_inline: int = 200,
    max_table_columns: int = 10,
    max_list_items: int = 200,
) -> str:
    """Convert a JSON-serializable Python value to Markdown.

    Parameters:
    - data: dict/list/primitive JSON-like structure
    - title: optional title rendered as a heading at the top
    - heading_level: base heading level for nested dict sections (>=1)
    - sort_keys: sort dict keys for stable output
    - max_string_inline: threshold before strings become code blocks
    - max_table_columns: cap columns when rendering list-of-dicts tables
    - max_list_items: truncate very large lists with a note
    """
    # If given a JSON string, attempt to parse first for structured rendering
    if isinstance(data, str):
        s = data.strip()
        if not s:
            return "(empty)\n"
        if s.startswith("{") or s.startswith("["):
            try:
                parsed = json.loads(s)
                return json_to_markdown(
                    parsed,
                    title=title,
                    heading_level=heading_level,
                    sort_keys=sort_keys,
                    max_string_inline=max_string_inline,
                    max_table_columns=max_table_columns,
                    max_list_items=max_list_items,
                )
            except Exception:
                # fall through and treat as plain string
                pass

    lines: list[str] = []

    def render(value: Any, level: int) -> None:
        # Dict -> section with bullet primitives + nested sections
        if isinstance(value, dict):
            # First, render primitive key-values as bullets for compactness
            keys = list(value.keys())
            if sort_keys:
                keys.sort()
            primitive_pairs: list[tuple[str, Any]] = []
            nonprimitive_pairs: list[tuple[str, Any]] = []
            for k in keys:
                v = value[k]
                if isinstance(v, Primitive):
                    primitive_pairs.append((k, v))
                else:
                    nonprimitive_pairs.append((k, v))

            if primitive_pairs:
                for k, v in primitive_pairs:
                    lines.append(f"- {k}: {_stringify(v, code_block_threshold=max_string_inline)}")

            for k, v in nonprimitive_pairs:
                hdr = max(1, min(6, level))
                lines.append("#" * hdr + f" {k}")
                render(v, level + 1)
            return

        # List -> bullets or table
        if isinstance(value, list):
            if not value:
                lines.append("- (empty)")
                return
            # Truncate very large lists
            items = value[:max_list_items]
            is_all_primitives = _all_primitives(items)
            if is_all_primitives:
                for it in items:
                    lines.append(f"- {_stringify(it, code_block_threshold=max_string_inline)}")
                if len(value) > max_list_items:
                    lines.append(f"... ({len(value) - max_list_items} more items omitted)")
                return

            if _all_dicts(items):
                rows: list[dict] = items  # type: ignore[assignment]
                keys = _common_primitive_keys(rows)
                if keys and len(keys) <= max_table_columns:
                    lines.extend(_render_table(rows, keys))
                    if len(value) > max_list_items:
                        lines.append(f"... ({len(value) - max_list_items} more rows omitted)")
                    # For any non-primitive fields, render nested under each item as needed
                    complex_keys = [
                        k for k in rows[0].keys() if k not in keys
                    ]
                    if complex_keys:
                        for idx, row in enumerate(rows):
                            complex_fields = {k: row[k] for k in complex_keys if k in row}
                            if complex_fields:
                                lines.append(f"\nItem {idx}")
                                render(complex_fields, level + 1)
                    return

            # Fallback: index and render each element
            for idx, it in enumerate(items):
                lines.append(f"- Item {idx}")
                render(it, level + 1)
            if len(value) > max_list_items:
                lines.append(f"... ({len(value) - max_list_items} more items omitted)")
            return

        # Primitive
        lines.append(_stringify(value, code_block_threshold=max_string_inline))

    if title:
        lvl = max(1, min(6, heading_level))
        lines.append("#" * lvl + f" {title}")

    render(data, heading_level + (1 if title else 0))
    return "\n".join(lines) + "\n"
