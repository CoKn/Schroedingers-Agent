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
                    json_mode=True)(TEMPLATE_V2)
]