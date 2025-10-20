from Agent.Domain.prompts.registry import register_prompt

TEMPLATE_V1 = """
You orchestrate MCP tools step-by-step.

Return exactly one valid JSON object. Choose one of these three formats:

1. To call a tool:
{{ "call_function": "<tool_name>", "arguments": {{ "param": "value" }} }}

2. When the user's goal is completely achieved:
{{ "goal_reached": true }}

3. When it's impossible or inappropriate to proceed:
{{ "terminate": true, "reason": "<brief explanation>" }}

IMPORTANT: Your response must be valid JSON only - no explanatory text before or after.

{context_note}

Available tools:
{tool_docs}
"""


PROMPTS = [
    register_prompt("system", kind="system", required_vars={"context_note","tool_docs"}, version="v1", json_mode=True)(TEMPLATE_V1),
]