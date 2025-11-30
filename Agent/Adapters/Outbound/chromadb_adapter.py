"""Adapter that lets the agent use ChromaDB as its vector memory store."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence
import logging

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings

from pathlib import Path

from Agent.Ports.Outbound.memory_interface import Memory

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


class ChromadbAdapter(Memory):
    """Concrete Memory implementation backed by ChromaDB collections."""

    persist_directory: str | None = None
    client_settings: Settings | None = None
    metadata: dict[str, Any] | None = None
    embedding_function: Any | None = None

    _client: ClientAPI | None = None
    _collections: dict[str, Collection] = {}

    async def connect(self, collection_name: str) -> Collection:
        """Create (or fetch) a collection with the provided name."""

        if collection_name in self._collections:
            return self._collections[collection_name]

        if self._client is None:
            settings = self.client_settings
            persist_path: str | None = None

            if self.persist_directory:
                persist_dir = Path(self.persist_directory).expanduser()
                persist_dir.mkdir(parents=True, exist_ok=True)
                persist_path = str(persist_dir)

                if settings is None:
                    settings = Settings(persist_directory=persist_path, 
                                        anonymized_telemetry=False)

            self._client = chromadb.PersistentClient(
                path=persist_path,
                settings=settings,
            )
            logger.info(self._client.heartbeat())

        collection = await asyncio.to_thread(
            self._client.get_or_create_collection,
            name=collection_name,
            metadata=self.metadata,
            embedding_function=self.embedding_function,
        )
        self._collections[collection_name] = collection
        return collection

    async def disconnect(self, collection_name: str | None = None) -> None:
        """Dispose of cached collections (optionally per collection)."""

        if collection_name:
            self._collections.pop(collection_name, None)
            return

        self._collections.clear()
        self._client = None

    async def query(
        self,
        collection_name: str,
        query_texts: Sequence[str] | None = None,
        *,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        include: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Query the requested collection for the closest matches."""

        collection = await self._get_collection(collection_name)
        query_payload = {
            "query_texts": query_texts or [],
            "n_results": max(1, n_results),
            "where": where,
            "include": include,
        }

        return await asyncio.to_thread(collection.query, **query_payload)

    async def save(
        self,
        collection_name: str,
        *,
        ids: Sequence[str],
        documents: Sequence[str] | None = None,
        metadatas: Sequence[dict[str, Any]] | None = None,
        embeddings: Sequence[Sequence[float]] | None = None,
    ) -> None:
        """Persist the provided vectors and metadata in the collection."""

        if not ids:
            raise ValueError("ids must contain at least one identifier")

        collection = await self._get_collection(collection_name)
        await asyncio.to_thread(
            collection.upsert,
            ids=list(ids),
            documents=list(documents) if documents else None,
            metadatas=list(metadatas) if metadatas else None,
            embeddings=list(embeddings) if embeddings else None,
        )

    async def _get_collection(self, collection_name: str) -> Collection:
        if collection_name not in self._collections:
            await self.connect(collection_name)
        return self._collections[collection_name]