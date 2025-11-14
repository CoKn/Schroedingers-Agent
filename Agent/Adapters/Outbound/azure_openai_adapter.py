from Agent.Ports.Outbound.llm_interface import LLM
from openai import AzureOpenAI, OpenAIError
from pydantic import BaseModel, PrivateAttr
from typing import Optional
import asyncio

class AzureOpenAIAdapter(LLM, BaseModel):
    api_key: str
    endpoint: str
    deployment_name: str
    api_version: Optional[str] = None
    _client: AzureOpenAI = PrivateAttr()

    def __init__(self, **data):
        super().__init__(**data)
        self._client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version
        )

    def call(self, prompt, system_prompt, json_mode: bool=False, max_tokens: int=20000, temperature: int=0, top_p: int=1) -> str:
        if json_mode:
            response_type = 'json_object'
        else:
            response_type = 'text'
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            response = self._client.chat.completions.create(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                response_format={"type": response_type},
                model=self.deployment_name
            )

            return response.choices[0].message.content
        except OpenAIError as e:
            return f"An Azure error occurred: {e}"

    async def call_stream(
        self, 
        prompt: str, 
        system_prompt: str, 
        json_mode: bool = False, 
        max_tokens: int = 20000, 
        temperature: int = 0, 
        top_p: int = 1
    ):
        """Streams the chat completion response from Azure OpenAI."""
        if json_mode:
            response_type = 'json_object'
        else:
            response_type = 'text'
        
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            
            stream = self._client.chat.completions.create(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                response_format={"type": response_type},
                model=self.deployment_name,
                stream=True 
            )
            
            collected_chunks = []
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    collected_chunks.append(content)
                    yield content
                    await asyncio.sleep(0) 
                    
            full_response = ''.join(collected_chunks)
            yield {"complete": True, "result": full_response}
                
        except OpenAIError as e:
            yield {"error": f"An Azure error occurred: {e}"}
