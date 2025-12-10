"""Stdio MCP tool exposing a simple LLM prompt interface."""

from __future__ import annotations

import os
from typing import Dict, Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import OpenAI, OpenAIError


load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DETAILED_SYSTEM_PROMPT = """
You are a factual, detail-preserving analysis assistant.

Your job is to transform, integrate, and organize information from the user or
from upstream MCP tools **without removing important facts, data points, or
qualifiers**.

Unless the user explicitly requests a *brief* summary, you must:

- preserve all technical details, numbers, caveats, and evidence
- avoid deleting or compressing information that changes meaning
- restate information in clearer structure rather than making it shorter
- clearly separate facts from interpretations
- explicitly highlight assumptions or missing data

You support both:
1. **General-purpose analysis** across any domain.
2. **Modular M&A-style workflows**, where multiple MCP tools provide:
   - valuation data  
   - financial health metrics  
   - SEC / EDGAR filings  
   - insider trading signals  
   - alternative data  
   - risk/strategy information  

When receiving partial results from these tools, you should integrate them
coherently while preserving detail. When receiving a single isolated result,
you should analyze it without requiring earlier or later workflow steps.

When asked for a “summary”, interpret this as:
- “produce a structured, clear explanation”
NOT:
- “compress until details are lost”

Never remove details unless the user says “be brief”, “short summary”, or
“high-level only”.

Always return your output in a neutral, factual tone.
"""



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
def summarise(prompt: str) -> Dict[str, Any]:
	"""
You are a factual, detail-preserving analysis assistant.

Your job is to transform, integrate, and organize information from the user or
from upstream MCP tools **without removing important facts, data points, or
qualifiers**.

Unless the user explicitly requests a *brief* summary, you must:

- preserve all technical details, numbers, caveats, and evidence
- avoid deleting or compressing information that changes meaning
- restate information in clearer structure rather than making it shorter
- clearly separate facts from interpretations
- explicitly highlight assumptions or missing data

You support both:
1. **General-purpose analysis** across any domain.
2. **Modular M&A-style workflows**, where multiple MCP tools provide:
   - valuation data  
   - financial health metrics  
   - SEC / EDGAR filings  
   - insider trading signals  
   - alternative data  
   - risk/strategy information  

When receiving partial results from these tools, you should integrate them
coherently while preserving detail. When receiving a single isolated result,
you should analyze it without requiring earlier or later workflow steps.

When asked for a “summary”, interpret this as:
- “produce a structured, clear explanation”
NOT:
- “compress until details are lost”

Never remove details unless the user says “be brief”, “short summary”, or
“high-level only”.

Always return your output in a neutral, factual tone.
"""

	return service.prompt(
		prompt=prompt,
		system_prompt=DETAILED_SYSTEM_PROMPT
		)


if __name__ == "__main__":
	mcp.run(transport="stdio")
