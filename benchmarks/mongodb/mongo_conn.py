"""
benchmarks/mongodb/mongo_conn.py — MongoDB Connection Helper
=============================================================
Mirrors the pattern of benchmarks/postgres/pg_conn.py.

Provides a single get_db() function that returns a pymongo Database
object connected to the dissertation MongoDB instance.

Usage:
    from mongo_conn import get_db

    db = get_db()
    doc = db["invoices"].find_one({"_id": some_id})
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """
    Return a module-level singleton MongoClient.
    Safe to call repeatedly — only one connection is created.
    """
    global _client
    if _client is None:
        user     = os.getenv("MONGO_USER")
        password = os.getenv("MONGO_PASSWORD")
        _client  = MongoClient(
            f"mongodb://{user}:{password}@localhost:27017/",
            serverSelectionTimeoutMS=5_000,
        )
    return _client


def get_db():
    """
    Return the dissertation pymongo Database object.
    The database name is read from MONGO_DB in .env.
    """
    db_name = os.getenv("MONGO_DB", "dissertation")
    return get_client()[db_name]