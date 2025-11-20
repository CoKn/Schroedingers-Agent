"""Stdio MCP tool exposing a simple LLM prompt interface."""

from __future__ import annotations

import os
from typing import Dict, Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import OpenAI, OpenAIError


load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


class PromptService:
	"""Sends prompts directly to the OpenAI chat completions endpoint."""

	def __init__(self) -> None:
		api_key = os.getenv("OPENAI_API_KEY")
		if not api_key:
			raise RuntimeError("Missing OPENAI_API_KEY environment variable.")
		self._client = OpenAI(api_key=api_key)

	def prompt(
		self,
		prompt: str,
		system_prompt: str | None = None,
		model: str | None = None,
		json_mode: bool = False,
		max_tokens: int = 2048,
		temperature: float = 0.2,
		top_p: float = 1.0,
	) -> Dict[str, Any]:
		chosen_model = model or DEFAULT_MODEL
		response_type = "json_object" if json_mode else "text"
		messages = [
			{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
			{"role": "user", "content": prompt},
		]
		try:
			completion = self._client.chat.completions.create(
				messages=messages,
				model=chosen_model,
				max_tokens=max_tokens,
				temperature=temperature,
				top_p=top_p,
				response_format={"type": response_type},
			)
			content = completion.choices[0].message.content
		except OpenAIError as exc:
			content = f"OpenAI error: {exc}"
		return {
			"response": content,
			"model": chosen_model,
			"json_mode": json_mode,
			"temperature": temperature,
			"top_p": top_p,
			"max_tokens": max_tokens,
		}


mcp = FastMCP(name="LLM Prompter", json_response=True)
service = PromptService()


@mcp.tool()
def prompt_llm(
	prompt: str,
	system_prompt: str | None = None,
	model: str | None = None,
	json_mode: bool = False,
	max_tokens: int = 2048,
	temperature: float = 0.2,
	top_p: float = 1.0,
) -> Dict[str, Any]:
	"""Send a prompt to an OpenAI chat model and return the response."""

	if max_tokens <= 0:
		return {"error": "max_tokens must be positive."}
	if not prompt.strip():
		return {"error": "prompt cannot be empty."}
	if temperature < 0 or temperature > 2:
		return {"error": "temperature must be between 0 and 2."}
	if top_p <= 0 or top_p > 1:
		return {"error": "top_p must be within (0, 1]."}

	return service.prompt(
		prompt=prompt,
		system_prompt=system_prompt,
		model=model,
		json_mode=json_mode,
		max_tokens=max_tokens,
		temperature=temperature,
		top_p=top_p,
	)


if __name__ == "__main__":
	mcp.run(transport="stdio")
