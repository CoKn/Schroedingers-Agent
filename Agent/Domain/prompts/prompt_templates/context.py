from Agent.Domain.prompts.registry import register_prompt


TEMPLATE_V1 = """
Goal: ({user_prompt}) previous step ({step_index}): tool={prev_tool} produced: {last_observation}
Choose the NEXT best tool toward the user's goal. Avoid repeating the same tool consecutively unless needed.
Before selecting a tool, evaluate if the goal is already achieved or blocked by missing user input or external constraints.
- If blocked, do NOT proceed with operational actions that depend on that input.
- Instead, either return {{ "terminate": true, "reason": "explanation" }} to stop, or choose a communication tool like send_message to request the needed information.
- If the assumed preconditions for the next step (listed below if available) are not satisfied, immediately return {{ "terminate": true, "reason": "Preconditions not met for next step" }}. Do not select or execute any tool.
- If all goals are achieved, return {{ "goal_reached": true }}. 
Do NOT terminate unless (a) no available tool can make progress, or (b) the preconditions for the next step are not met.

Observation History:
{observation_history}
"""

# just for testing
TEMPLATE_V2 = """
Goal: ({user_prompt}) previous step ({step_index}): tool={prev_tool} produced: {last_observation}
Choose the NEXT best tool toward the user's goal. Avoid repeating the same tool consecutively unless needed.
Before selecting a tool, evaluate if the goal is already achieved or blocked by missing user input or external constraints.
- If blocked, do NOT proceed with operational actions that depend on that input.
- Instead, either return {{ "terminate": true, "reason": "explanation" }} to stop, or choose a communication tool like send_message to request the needed information.
- If the assumed preconditions for the next step (listed below if available) are not satisfied, immediately return {{ "terminate": true, "reason": "Preconditions not met for next step" }}. Do not select or execute any tool.
- If all goals are achieved, return {{ "goal_reached": true }}. 
Do NOT terminate unless (a) no available tool can make progress, or (b) the preconditions for the next step are not met.

Observation History:
{observation_history}
"""


PROMPTS = [
    register_prompt("context", kind="system", required_vars={"user_prompt","step_index", "prev_tool", "last_observation", "observation_history"}, version="v1", json_mode=True)(TEMPLATE_V1),
    register_prompt("context", kind="system", required_vars={"user_prompt","step_index", "prev_tool", "last_observation", "observation_history"}, version="v1", json_mode=True)(TEMPLATE_V2)
]