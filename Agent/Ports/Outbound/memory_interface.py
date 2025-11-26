from pydantic import BaseModel, ConfigDict
from abc import ABC, abstractmethod


class Memory(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def connect(self):
        ...

    @abstractmethod
    async def disconnect(self):
        ...

    @abstractmethod
    async def query(self):
        ...

    
