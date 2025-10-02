context_prompt = """
Goal: ({user_prompt}) previous step ({step_index}): tool={prev_tool} produced: {last_observation}
Choose the NEXT best tool toward the user's goal. Avoid repeating the same tool consecutively unless needed.
Before selecting a tool, evaluate if the goal is already achieved or blocked by missing user input or external constraints.
- If blocked, do NOT proceed with operational actions that depend on that input.
- Instead, either return {{ "terminate": true, "reason": "explanation" }} to stop, or choose a communication tool like send_message to request the needed information.
- If all goals are achieved, return {{ "goal_reached": true }}. 
Do NOT terminate unless no available tool can make progress.

"""