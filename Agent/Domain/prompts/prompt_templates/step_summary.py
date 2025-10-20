# Agent/Domain/prompts/prompt_templates/step_summary.py
from Agent.Domain.prompts.registry import register_prompt

TEMPLATE_V1 = """Original query: {user_prompt}
Current goal: {current_goal}

Assumed preconditions:
{preconditions_block}

Assumed effects:
{effects_block}

Chosen tool: {tool} 

with args: 
{args}

Tool returned: 
{last_observation}

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
"""

#TODO: adjust the prompt so that it inlcudes the facts that can be extracted from the env feedback

PROMPTS = [
    register_prompt("step_summary", 
                    kind="user", 
                    required_vars={"user_prompt", "current_goal", "preconditions_block", "effects_block", "tool", "args", "last_observation"}, 
                    version="v1", 
                    json_mode=False)(TEMPLATE_V1),
]