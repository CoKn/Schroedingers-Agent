from Agent.Ports.Outbound.llm_interface import LLM
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, PrivateAttr
import asyncio


class OpenAIAdapter(LLM, BaseModel):
    """
    Adapter for the public OpenAI API.
    Mirrors the interface of AzureOpenAIAdapter for drop-in replacement.
    """
    api_key: str
    deployment_name: str
    _client: OpenAI = PrivateAttr()

    def __init__(self, **data):
        super().__init__(**data)
        self._client = OpenAI(
            api_key=self.api_key
        )

    def call(
        self,
        prompt: str,
        system_prompt: str,
        json_mode: bool = False,
        max_tokens: int = 16384,
        temperature: float = 0,
        top_p: float = 1
    ) -> str:
        """
        Synchronous one-shot completion.
        """
        response_type = "json_object" if json_mode else "text"
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            resp = self._client.chat.completions.create(
                messages=messages,
                model=self.deployment_name,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                response_format={"type": response_type},
            )
            return resp.choices[0].message.content
        except OpenAIError as e:
            return f"An OpenAI error occurred: {e}"

    async def call_stream(
        self,
        prompt: str,
        system_prompt: str,
        json_mode: bool = False,
        max_tokens: int = 16384,
        temperature: float = 0,
        top_p: float = 1
    ):
        """
        Async generator streaming tokens/chunks.
        Yields str chunks, then a final dict { 'complete': True, 'result': full_text }.
        """
        response_type = "json_object" if json_mode else "text"
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            stream = self._client.chat.completions.create(
                messages=messages,
                model=self.deployment_name,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                response_format={"type": response_type},
                stream=True
            )
            collected = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    piece = chunk.choices[0].delta.content
                    collected.append(piece)
                    yield piece
                    await asyncio.sleep(0)
            full = "".join(collected)
            yield {"complete": True, "result": full}
        except OpenAIError as e:
            yield {"error": f"An OpenAI error occurred: {e}"}