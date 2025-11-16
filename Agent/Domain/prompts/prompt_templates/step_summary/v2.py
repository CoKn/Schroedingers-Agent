"""
Original query:
{user_prompt}

Current goal:
{current_goal}

Assumed preconditions:
{preconditions_block}

Assumed effects:
{effects_block}

Chosen tool:
{tool}

with args:
{args}

Tool returned:
{last_observation}

Entire Plan:
{plan}

INSTRUCTIONS (READ CAREFULLY):
- Your entire response MUST be a single valid JSON object and NOTHING ELSE (no prose, no bullet points, no code fences).
- Use the schema below EXACTLY. Do not add or remove fields.
- Strings use double quotes; booleans are true/false; use null when unknown.
- Arrays must not contain comments. No trailing commas.
- When uncertain, treat items as unmet/missing.
- Extract concrete values ONLY from "Tool returned" and other provided sections above; do not invent data.

SCHEMA (OUTPUT MUST MATCH THIS EXACTLY):
{{
    "summary": "Concise outcome in one or two sentences.",
    "preconditions_check": {{
    "met": ["precondition A", "precondition B"],
    "unmet": ["precondition X", "precondition Y"]
    }},
    "effects_status": {{
    "achieved": ["Effect: value(s) with IDs/URLs/timestamps/etc."],
    "missing": ["effect still needed 1", "effect still needed 2"]
    }},
    "ready_to_proceed": true,
    "justification": "One short sentence explaining why (or why not).",
    "extracted_results": [
    {{ "name": "Title", "value": "..." }},
    {{ "name": "URL", "value": "..." }},
    {{ "name": "ID", "value": "..." }}
    ],
    "preconditions": [
    {{
        "assumed_title": "assumed precondition 1",
        "actual_title": "actual precondition 1",
        "met": true,
        "note": "short note or null"
    }}
    ],
    "effects": [
    {{
        "assumed_title": "assumed effect 1",
        "actual_title": "actual effect 1",
        "achieved": true,
        "values": ["ID: 123", "URL: https://example.com"],
        "note": "short note or null"
    }}
    ],
    "facts_generated": [
    "fact 1",
    "fact 2"
    ]
}}
"""