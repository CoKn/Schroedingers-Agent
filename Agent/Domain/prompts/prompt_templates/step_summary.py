# Agent/Domain/prompts/prompt_templates/step_summary.py
from Agent.Domain.prompts.registry import register_prompt

TEMPLATE_V1 = """
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

    Instructions:
    First, summarise the outcome in plain text. Then output the following sections EXACTLY with clear
    bullet lists, based ONLY on the evidence above (if uncertain, treat as unmet/missing):

    Preconditions check:
    - Met:
      - List preconditions fully satisfied. If none, write 'None'.
    - Unmet:
      - List preconditions that are not satisfied or only partially satisfied. If uncertain, include them here.
        If none, write 'None'.

    Effects status:
    - Achieved:
      - List target effects achieved. If none, write 'None'.
    - Missing:
      - List target effects not yet achieved. If uncertain, include them here. If none, write 'None'.

    Ready to proceed: yes/no
    - Choose 'no' if any preconditions are unmet or key effects are missing. Provide one-sentence justification.

    Facts to know for further steps:
    - List all facts that could be relevant for further steps 

    """

TEMPLATE_V2 = """
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

TEMPLATE_V3 = """
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
- If "Tool returned" contains structured data (JSON, markdown tables, or obvious lists of records), you MUST:
  - Inspect arrays named things like "results", "items", "rows", "records" or similar.
  - Treat each element in such arrays as a distinct record/entity.
  - Extract human-meaningful attributes such as names, titles, IDs, URLs, statuses, etc.
  - Use those attributes in "extracted_results", "effects", and "facts_generated" when relevant to the current goal.
- If "Tool returned" is markdown and includes tables (lines starting with `|`), treat each row as a record and extract the important columns as facts.
- If "Tool returned" contains long text with embedded JSON or table-like blocks (for example between tags like `<data-source-state> ... </data-source-state>` or `CREATE TABLE ...`), treat those as structured hints:
  - Extract field names, IDs, and other key metadata as facts.
  - Do NOT hallucinate values that are not present.

- "facts_generated":
  - This is the main place to store NEW, REUSABLE FACTS discovered in this step.
  - Always include 3-10 short, atomic statements when possible.
  - Each fact should be:
    - self-contained (can be understood without the rest of the JSON),
    - directly supported by "Tool returned" or other given context.
  - Prioritise facts that:
    - Describe what data was retrieved (e.g. key fields, row counts, important item properties),
    - Summarise any tables or lists (e.g. "Found 12 items with fields: Name, URL, Status."),
    - Capture error conditions (e.g. "Request failed with 400 validation_error: ..."),
    - Indicate presence or absence of expected data (e.g. "No list of items was returned; only metadata and schema were provided.").
  - When you see a table or list of structured items (rows/objects), especially under keys like "results", "items", "rows", "records", "pages":
    - Add at least one fact summarising the size and columns (e.g. "Found 10 results with fields: id, title, url, type, timestamp."),
    - AND, if the goal is to list or collect these items, add one fact per item for at least the first 10-20 items, using their identifiers (title/name) and any IDs/URLs.
  - Do NOT invent items or fields that are not present; if something is expected but missing, state that explicitly as a fact.


OUTPUT SCHEMA EXAMPLE (DO NOT COPY LITERALLY; FILL WITH REAL VALUES):

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
    {{ "name": "Key attribute 1", "value": "..." }},
    {{ "name": "Key attribute 2", "value": "..." }}
  ],
  "preconditions": [
    {{
      "assumed_title": "assumed precondition 1",
      "actual_title": "actual precondition 1 (or null if not mentioned)",
      "met": true,
      "note": "short note or null"
    }}
  ],
  "effects": [
    {{
      "assumed_title": "assumed effect 1",
      "actual_title": "actual effect 1 (or null if not mentioned)",
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




PROMPTS = [
    register_prompt("step_summary", 
                    kind="user", 
                    required_vars={"user_prompt", "current_goal", "preconditions_block", "effects_block", "tool", "args", "last_observation"}, 
                    version="v1", 
                    json_mode=False)(TEMPLATE_V1),
    register_prompt("step_summary", 
                    kind="user", 
                    required_vars={"user_prompt", "current_goal", "preconditions_block", "effects_block", "tool", "args", "last_observation", "plan"}, 
                    version="v2", 
                    json_mode=True)(TEMPLATE_V2),
    register_prompt("step_summary", 
                    kind="user", 
                    required_vars={"user_prompt", "current_goal", "preconditions_block", "effects_block", "tool", "args", "last_observation", "plan"}, 
                    version="v3", 
                    json_mode=True)(TEMPLATE_V3)
]