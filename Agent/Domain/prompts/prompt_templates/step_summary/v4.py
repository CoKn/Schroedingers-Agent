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
- If "Tool returned" contains structured data (JSON, markdown tables, or obvious lists of records), you MUST:
  - Inspect arrays named things like "results", "items", "rows", "records" or similar.
  - Treat each element in such arrays as a distinct record/entity.
  - Extract human-meaningful attributes such as names, titles, IDs, URLs, statuses, etc.
  - Use those attributes in "extracted_results", "effects", and "facts_generated" when relevant to the current goal.
- If "Tool returned" is markdown and includes tables (lines starting with `|`), treat each row as a record and extract the important columns as facts.
- If "Tool returned" contains long text with embedded JSON or table-like blocks (for example between tags like `<data-source-state> ... </data-source-state>` or `CREATE TABLE ...`), treat those as structured hints:
  - Extract field names, IDs, and other key metadata as facts.
  - Do NOT hallucinate values that are not present.

- CROSS-STEP INFORMATION RETENTION (IMPORTANT):
  - Treat all items in "Assumed preconditions" and "Assumed effects" as signals of information that may be needed in LATER steps of the plan, not just the current goal.
  - Use "Entire Plan" to infer which entities will be referenced, updated, or queried in future steps.
  - Whenever "Tool returned" contains data that can satisfy ANY precondition/effect (especially those mentioning things like "ID is known", "URL is known", "handle is available", "mapping between X and Y is known"):
    - Mark the corresponding preconditions as met in "preconditions_check" and in the "preconditions" array where appropriate.
    - Add explicit, atomic facts to "facts_generated" that record this information, including both human-readable labels (e.g. names/titles) AND their unique identifiers (IDs, URLs, primary keys).
    - Add corresponding entries to "extracted_results" so that later steps can easily reuse these identifiers.
  - For lists/tables of entities that are likely to be used later (e.g. pages, records, companies, users), store for each entity at least its name/title AND any unique identifiers (ID, URL, primary key) for as many entities as is reasonable (e.g. first 10–20).
  - NEVER drop or omit IDs/URLs or other unique identifiers just because they are not directly required to complete the current step; they may be critical for satisfying future preconditions and effects.

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
