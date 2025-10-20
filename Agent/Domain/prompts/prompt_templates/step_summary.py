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
  - For each achieved effect, include the specific values found in the tool output (IDs, URLs, file paths, titles, counts with units, timestamps, key fields from JSON, short excerpts). Use the format: "Effect: value(s)". If none, write 'None'.
- Missing:
  - List target effects not yet achieved. If uncertain, include them here. If none, write 'None'.

Ready to proceed: yes/no
- Choose 'no' if any preconditions are unmet or key effects are missing. Provide one-sentence justification.

Extracted results (from tool output):
- List concrete data points discovered in "Tool returned" using "name: value" format.
- Include, where applicable: IDs, URLs, file paths, counts/sizes with units, timestamps, titles, key-value pairs from JSON, and the top 3 items for lists.
- If the output is textual, include a 1-2 line concise excerpt capturing the answer (no more than 200 characters).
- If nothing extractable, write 'None'.

Facts to know for further steps:
- List all facts that could be relevant for further steps. Consider both the current and all future tasks.
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
                    json_mode=False)(TEMPLATE_V2),
]