from pydantic import BaseModel, ConfigDict
from abc import ABC, abstractmethod


class MCPClient(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def connect(self):
        ...

    @abstractmethod
    async def disconnect(self):
        ...
