#!/usr/bin/env python
# coding: utf-8 -*-
from __future__ import annotations

from typing import Any, List, Tuple, cast

from chromadb import EmbeddingFunction, HttpClient, IDs, PersistentClient
from chromadb.api import ClientAPI
from chromadb.api.collection_configuration import CreateCollectionConfiguration
from chromadb.api.types import (
    ID,
    Document,
    Documents,
    Embeddable,
    Embedding,
    Embeddings,
    Metadata,
    OneOrMany,
)
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from openai import OpenAI


class BaseEmbedDB:
    """Wrapper for Chroma database, which uses Embeddings to search for documents."""

    client: ClientAPI
    embedFn: EmbeddingFunction[Embeddable]

    def __init__(self, client: ClientAPI, embFn: EmbeddingFunction) -> None:
        self.client = client
        self.embedFn = embFn
        self.__collection_config: CreateCollectionConfiguration = {
            "hnsw": {"space": "cosine"},
        }

    @classmethod
    def createFromPath(
        cls, path: str, embFn: EmbeddingFunction
    ) -> BaseEmbedDB:
        return cls(PersistentClient(path), embFn)

    @classmethod
    def createFromHttps(
        cls, url: str, port: int, embFn: EmbeddingFunction
    ) -> BaseEmbedDB:
        return cls(HttpClient(url, port), embFn)

    def requestdoclist_embed(
        self,
        collection: str,
        embeddings: Embeddings,
        query: dict = {},
        n: int = 3,
    ) -> List[Tuple[Any]]:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )

        if coll.count() == 0:
            return []

        q_results = (
            coll.query(
                query_embeddings=embeddings,
                n_results=n,
                include=["embeddings", "metadatas", "documents", "distances"],
            )
            if not query
            else coll.query(
                query_embeddings=embeddings,
                n_results=n,
                where=query,
                include=["embeddings", "metadatas", "documents", "distances"],
            )
        )

        return [
            (
                q_results["ids"][i][j],
                q_results["documents"][i][j],  # type: ignore
                q_results["distances"][i][j],  # type: ignore
                q_results["metadatas"][i][j],  # type: ignore
                q_results["embeddings"][i][j],  # type: ignore
            )
            for i in range(len(embeddings))
            for j in range(len(q_results["ids"][i]))
        ]

    def requestdoclist_text(
        self,
        collection: str,
        query_texts: List[str],
        query: dict = {},
        n: int = 3,
    ) -> List[tuple]:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )

        if coll.count() == 0:
            return []

        q_results = (
            coll.query(
                query_texts=query_texts,
                n_results=n,
                include=["embeddings", "metadatas", "documents", "distances"],
            )
            if not query
            else coll.query(
                query_texts=query_texts,
                n_results=n,
                where=query,
                include=["embeddings", "metadatas", "documents", "distances"],
            )
        )

        return [
            (
                q_results["ids"][i][j],
                q_results["documents"][i][j],  # type: ignore
                q_results["distances"][i][j],  # type: ignore
                q_results["metadatas"][i][j],  # type: ignore
                q_results["embeddings"][i][j],  # type: ignore
            )
            for i in range(len(query_texts))
            for j in range(len(q_results["ids"][i]))
        ]

    def deletedocs(self, collection: str, ids: IDs) -> None:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )
        coll.delete(ids)

    def clear_collection(self, collection: str) -> None:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )

        if coll.count() == 0:
            return

        ids = coll.get()["ids"]
        if ids:
            coll.delete(ids=ids)

    def upsert(
        self,
        collection: str,
        doc_ids: OneOrMany[ID],
        doc_contents: OneOrMany[Document],
        doc_metadatas: OneOrMany[Metadata] | None = None,
        doc_embeddings: OneOrMany[Embedding] | None = None,
    ) -> None:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )
        coll.upsert(
            ids=doc_ids,
            documents=doc_contents,
            embeddings=doc_embeddings,
            metadatas=doc_metadatas,
        )

    def has_id(self, collection: str, doc_id: ID) -> bool:
        coll = self.client.get_or_create_collection(
            collection,
            configuration=self.__collection_config,
            embedding_function=self.embedFn,
        )
        res = coll.get(ids=[doc_id])

        return doc_id in res["ids"]


class LocalEmbeddingFunction(EmbeddingFunction[Embeddable]):
    def __init__(self, url: str, api_key: str, model: str):
        self.__url = url
        self.__api_key = api_key
        self.__model = model
        self.__client = OpenAI(base_url=self.__url, api_key=self.__api_key)

    def __call__(self, input: Documents) -> Embeddings:
        # replace newlines, which can negatively affect performance.
        input = [t.replace("\n", " ") for t in input]

        embeddings = self.__client.embeddings.create(
            input=input, model=self.__model
        ).data

        # Sort resulting embeddings by index
        sorted_embeddings = sorted(embeddings, key=lambda e: e.index)

        # Return just the embeddings
        return cast(
            Embeddings, [result.embedding for result in sorted_embeddings]
        )


# class LocalEmbedDB(BaseEmbedDB):
#     def __init__(
#         self, client: ClientAPI, url: str, api_key: str, model: str
#     ) -> None:
#         local_embed_fn = LocalEmbeddingFunction(url, api_key, model)
#         super().__init__(client, local_embed_fn)

#     @classmethod
#     def createFromPath(
#         cls, path: str, url: str, api_key: str, model: str
#     ) -> LocalEmbedDB:
#         return cls(PersistentClient(path), url, api_key, model)

#     @classmethod
#     def createFromHttps(
#         cls, db_url: str, port: int, emb_url: str, api_key: str, model: str
#     ) -> LocalEmbedDB:
#         return cls(HttpClient(db_url, port), emb_url, api_key, model)


class OpenAiEmbedDB(BaseEmbedDB):
    def __init__(
        self, client: ClientAPI, url: str, api_key: str, model: str, dims: int
    ) -> None:
        open_embed_fn = OpenAIEmbeddingFunction(
            api_key=api_key, model_name=model, api_base=url, dimensions=dims
        )

        super().__init__(client, open_embed_fn)

    @classmethod
    def createFromPath(
        cls, path: str, url: str, api_key: str, model: str, dims: int
    ) -> OpenAiEmbedDB:
        return cls(PersistentClient(path), url, api_key, model, dims)

    @classmethod
    def createFromHttps(
        cls,
        db_url: str,
        port: int,
        emb_url: str,
        api_key: str,
        model: str,
        dims,
    ) -> OpenAiEmbedDB:
        return cls(HttpClient(db_url, port), emb_url, api_key, model, dims)
