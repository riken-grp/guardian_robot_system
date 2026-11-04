#!/usr/bin/env python
# coding: utf-8 -*-
from chromadb import PersistentClient
from pyindy.llm.embed_db import OpenAIEmbeddingFunction, LocalEmbeddingFunction

# Run this file to copy a Chroma Database to a new location.
# It is also possible to change some of the settings (model name, etc.)

# 0. Set important info (location of databases, etc.)
ORIG_PATH = "~/.chromadb/indy1e/memorydb"
ORIG_API_URL = "http://localhost:8002/v1"
ORIG_API_KEY = "NONE"
ORIG_MODEL = "indy-instruct"
ORIG_EMBED_FN = LocalEmbeddingFunction(
    url=ORIG_API_URL, api_key=ORIG_API_KEY, model=ORIG_MODEL
)

NEW_PATH = "~/.chromadb/indy1e/memorydb_2"
NEW_API_URL = "http://localhost:8002/v1"
NEW_API_KEY = "NONE"
NEW_MODEL = "indy-instruct"
NEW_EMBED_FN = OpenAIEmbeddingFunction(
    api_base=NEW_API_URL, api_key=NEW_API_KEY, model_name=NEW_MODEL
)

COLLECTION_NAMES = ["narrative", "longterm"]

# 1. Create clients
orig_client = PersistentClient(path=ORIG_PATH)
new_client = PersistentClient(path=NEW_PATH)

for coll_name in COLLECTION_NAMES:
    # 2. Load collection objects
    orig_coll = orig_client.get_or_create_collection(
        coll_name, embedding_function=ORIG_EMBED_FN
    )
    new_coll = new_client.get_or_create_collection(
        coll_name,
        configuration={
            "embedding_function": NEW_EMBED_FN,
            "hnsw": {"space": "cosine"},
        },
    )

    # 3. Get all embeddings from Orig
    orig_embeddings = orig_coll.get(
        include=["metadatas", "documents", "embeddings"]
    )

    # 4. Add data
    new_coll.add(
        ids=orig_embeddings["ids"],
        embeddings=orig_embeddings["embeddings"],
        metadatas=orig_embeddings["metadatas"],
        documents=orig_embeddings["documents"],
    )
