"""
You are generating parameters for a pre-selected MCP tool to achieve a specific step in a larger plan.

Global user goal (for context):
{global_goal}

Current step goal:
{step_goal}

Step index: {step_index} of {max_steps}

Tool to use:
{tool_name}

Assumed preconditions for this step:
{preconditions}

Assumed effects for this step:
{effects}

Your job:
- Decide the arguments for calling this tool for the CURRENT STEP.
- Do NOT decide whether the entire global goal is completed.
- Only refuse to provide arguments if it is truly impossible to call the tool correctly.

Return EXACTLY ONE valid JSON object in this format:

1. Normal case - you can generate arguments:
{{
  "call_function": "{tool_name}",
  "arguments": {{ ... }}
}}

2. Only if it is impossible to call the tool safely or meaningfully:
{{
  "abort_step": true,
  "reason": "<brief explanation>"
}}

IMPORTANT:
- Never use "terminate": true or "reason": "goal completed" here.
- Focus on generating the next sensible parameters for this step.

"""
