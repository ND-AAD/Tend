"""Tests run against real PostgreSQL (SPEC §12). Each test gets a fresh database.
Set TEND_TEST_DSN to a server where the role may CREATE DATABASE."""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from tend.app import App
from tend.config import Config

ADMIN = os.environ.get("TEND_TEST_DSN", "postgresql://tend:tend@localhost/tend_dev")
OWNER = "person:nick@example.com"


@pytest.fixture
def cfg() -> Config:
    return Config(owner_id=OWNER, owner_identifiers=[OWNER, "person:gh:nd-aad"],
                  setup_at="2026-11-01-08:00")


@pytest.fixture
def app(cfg):
    name = "tend_t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = ADMIN.rsplit("/", 1)[0] + "/" + name
    cfg.database_url = dsn
    a = App(cfg)
    try:
        yield a
    finally:
        a.close()
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
