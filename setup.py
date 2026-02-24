"""
setup.py — Phase 0 Health Check
================================
Connects to all 7 databases and prints OK / FAIL for each.

Usage:
    python setup.py               # runs health check
    python setup.py --wait        # waits for all DBs to be ready (useful right after docker-compose up)

docker-compose up -d
python setup.py
--------------------
docker-compose down
"""

import sys
import time
import argparse
from dotenv import load_dotenv
import os

load_dotenv()

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

def ok(name):
    print(f"  {GREEN}✔ {name:<20} OK{RESET}")

def fail(name, error):
    print(f"  {RED}✘ {name:<20} FAIL — {error}{RESET}")

def warn(msg):
    print(f"  {YELLOW}⚠ {msg}{RESET}")

# ── individual checks ─────────────────────────────────────────────────────────

def check_postgres():
    import psycopg2
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB"),
        connect_timeout=5,
    )
    conn.close()
    ok("PostgreSQL")
    return True

def check_mongodb():
    from pymongo import MongoClient
    user = os.getenv("MONGO_USER")
    password = os.getenv("MONGO_PASSWORD")
    client = MongoClient(
        f"mongodb://{user}:{password}@localhost:27017/",
        serverSelectionTimeoutMS=5000,
    )
    client.admin.command("ping")
    client.close()
    ok("MongoDB")
    return True

def check_redis():
    import redis
    r = redis.Redis(
        host="localhost",
        port=6379,
        password=os.getenv("REDIS_PASSWORD"),
        socket_connect_timeout=5,
    )
    r.ping()
    ok("Redis")
    return True

def check_neo4j():
    from neo4j import GraphDatabase
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=(user, password),
        connection_timeout=5,
    )
    driver.verify_connectivity()
    driver.close()
    ok("Neo4j")
    return True

def check_elasticsearch():
    import urllib.request
    import json
    url = "http://localhost:9200/_cluster/health"
    with urllib.request.urlopen(url, timeout=5) as resp:
        health = json.loads(resp.read())
    if health["status"] == "red":
        raise RuntimeError(f"Cluster health is RED: {health}")
    ok("Elasticsearch")
    return True

def check_cassandra():
    from cassandra.cluster import Cluster
    from cassandra.auth import PlainTextAuthProvider
    auth = PlainTextAuthProvider(
        username=os.getenv("CASSANDRA_USER"),
        password=os.getenv("CASSANDRA_PASSWORD"),
    )
    cluster = Cluster(
        ["127.0.0.1"],
        port=9042,
        auth_provider=auth,
        connect_timeout=10,
    )
    session = cluster.connect()
    session.execute("SELECT release_version FROM system.local")
    cluster.shutdown()
    ok("Cassandra")
    return True

def check_timescaledb():
    import psycopg2
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        user=os.getenv("TIMESCALE_USER"),
        password=os.getenv("TIMESCALE_PASSWORD"),
        dbname=os.getenv("TIMESCALE_DB"),
        connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute("SELECT default_version FROM pg_available_extensions WHERE name = 'timescaledb';")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("timescaledb extension not available")
    conn.close()
    ok("TimescaleDB")
    return True

# ── runner ────────────────────────────────────────────────────────────────────

CHECKS = [
    ("PostgreSQL",     check_postgres),
    ("MongoDB",        check_mongodb),
    ("Redis",          check_redis),
    ("Neo4j",          check_neo4j),
    ("Elasticsearch",  check_elasticsearch),
    ("Cassandra",      check_cassandra),
    ("TimescaleDB",    check_timescaledb),
]

def run_checks(wait=False, max_wait_seconds=120):
    print("\n" + "═" * 50)
    print("  Dissertation — Database Health Check")
    print("═" * 50)

    results = {}
    deadline = time.time() + max_wait_seconds

    for name, check_fn in CHECKS:
        attempts = 0
        while True:
            attempts += 1
            try:
                check_fn()
                results[name] = True
                break
            except Exception as e:
                if wait and time.time() < deadline:
                    print(f"  {YELLOW}⟳ {name:<20} not ready yet, retrying in 5s...{RESET}")
                    time.sleep(5)
                else:
                    fail(name, str(e))
                    results[name] = False
                    break

    # ── summary ──
    print("\n" + "─" * 50)
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    print(f"  Result: {passed}/{total} databases reachable\n")

    if passed == total:
        print(f"  {GREEN}All systems GO — ready to proceed to Phase 1{RESET}\n")
        return 0
    else:
        failed = [name for name, v in results.items() if not v]
        print(f"  {RED}Fix the following before proceeding: {', '.join(failed)}{RESET}\n")
        if not wait:
            warn("Tip: run with --wait if containers are still starting up")
        return 1

# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dissertation DB health check")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Keep retrying for up to 2 minutes (useful right after docker-compose up)",
    )
    args = parser.parse_args()
    sys.exit(run_checks(wait=args.wait))