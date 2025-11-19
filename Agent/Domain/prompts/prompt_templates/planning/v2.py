"""
You are generating parameters for a pre-selected MCP tool to achieve a specific goal.

User goal:
{user_goal}

Step index: {step_index} of {max_steps}

Tool to use:
{tool_name}

Assumed preconditions for this step:
{preconditions}

Assumed effects for this step:
{effects}

Decide if any further action with this tool is required.

Return EXACTLY ONE valid JSON object, using ONE of the following formats:

1. When the goal associated with this step is completely achieved and no further tool calls are required:
{{ "terminate": true, "reason": "goal completed" }}

2. When it is impossible or inappropriate to proceed (for example, unmet preconditions, missing required input, tool limitations):
{{ "terminate": true, "reason": "<brief explanation>" }}

3. When a concrete action is still required and you should call the pre-selected tool with parameters:
{{ "call_function": "{tool_name}", "arguments": {{ "param": "value" }} }}

IMPORTANT:
- Respond with **valid JSON only** — no extra text before or after.
- Prefer option (1) or (2) when appropriate; only use option (3) when a real tool call is necessary.
- When generating `"arguments"` for option (3):
  - Respect the tool's expected parameter types and required fields.
  - Use the user goal, preconditions, effects, and context to choose sensible values.
  - If a parameter requires a specific index, you may start with reasonable defaults (e.g., `0` for the first item) when justified by the goal and context.
  - If multiple actions are possible, focus on the **next** most logical step, not all steps at once.
"""