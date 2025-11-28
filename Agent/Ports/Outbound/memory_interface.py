from pydantic import BaseModel, ConfigDict
from abc import ABC, abstractmethod


class Memory(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def connect(self, collection_name: str):
        ...

    @abstractmethod
    async def disconnect(self, collection_name: str | None = None):
        ...

    @abstractmethod
    async def query(self, collection_name: str, *args, **kwargs):
        ...

    @abstractmethod
    async def save(self, collection_name: str, *args, **kwargs):
        ...

    
