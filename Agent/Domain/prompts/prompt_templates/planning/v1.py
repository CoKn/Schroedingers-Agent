"""
User goal: {user_goal}
Tool to use: {tool_name}
Step index: {step_index} of {max_steps}.

{preconditions}
{effects}

Decide if further action is required.
Return EXACTLY ONE JSON object using one of these formats:

1) If the goal is already achieved:
   {{"goal_reached": true}}

2) If it's impossible/inappropriate to proceed (e.g., unmet preconditions or missing input):
   {{"terminate": true, "reason": "<brief>"}}

3) Otherwise, generate the tool call parameters:
   {{"call_function": "<tool_name>", "arguments": {{"param": "value"}}}}

Respond with valid JSON only — no extra text.
"""
