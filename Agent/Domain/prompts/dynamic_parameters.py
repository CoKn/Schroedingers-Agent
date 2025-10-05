dynamic_parameters_prompt = """
You are generating parameters for a pre-selected MCP tool to achieve a specific goal.

Your task is to generate appropriate parameters for the tool based on:
- The specific goal you need to achieve
- The tool's documentation and required parameters
- Any available context from previous steps

IMPORTANT: You MUST generate parameters. Do not terminate or refuse - find reasonable default values if specific information is missing.

Return exactly one valid JSON object in this format:
{{ "call_function": "<tool_name>", "arguments": {{ "param": "value" }} }}

Your response must be valid JSON only - no explanatory text before or after.

{context_note}

Tool to use:
{tool_docs}

Guidelines for parameter generation:
- If a parameter requires a specific value (like row/column index), start with reasonable defaults (e.g., 0 for first row/column)
- If multiple calls are needed, focus on the first logical step
- Use the goal description to infer appropriate parameter values
- When in doubt, choose values that allow exploration or investigation of the problem space
"""