#!/usr/bin/env python3
"""
Tenant seeding script — create or update tenant records in the DB.

Usage:
    python scripts/seed_tenants.py --tenant pashutomazia
    python scripts/seed_tenants.py --tenant iroko
    python scripts/seed_tenants.py --all

This script is idempotent: running it twice on the same tenant does
an upsert (update if exists, insert if not).

Environment:
    DATABASE_URL — async Postgres connection string

Example:
    DATABASE_URL="postgresql+asyncpg://user:pass@localhost/leadwise" \\
    python scripts/seed_tenants.py --tenant pashutomazia
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

# ─── Tenant definitions ───────────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent.parent / "data"


def _read_prompt(path: Path) -> str:
    """Read a system prompt file, return empty string if not found."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    print(f"  WARNING: prompt file not found: {path}")
    return ""


TENANT_CONFIGS = {
    "pashutomazia": {
        "id": "00000000-0000-0000-0000-000000000001",  # fixed UUID for seeding
        "slug": "pashutomazia",
        "name": "פשוטומציה",
        "graph_type": "pashutomazia",
        "llm_model": "anthropic/claude-sonnet-4-6",
        "qdrant_collection": "pashutomazia_knowledge",
        "rate_limit_rpm": 60,
        "extra_config": {
            "meeting_link_hot": "https://cal.com/pashutomazia-moshe/30min",
            "meeting_link_warm": "https://cal.com/pashutomazia-moshe/15min",
            "youtube_channel": "https://www.youtube.com/@pashutomazia",
            "free_lecture_url": "https://youtu.be/b1NLjLqJwBo",
            "min_project_budget_ils": 4750,
        },
        "system_prompt_file": PROMPTS_DIR / "pashutomazia" / "system_prompt.md",
    },
    "iroko": {
        "id": "00000000-0000-0000-0000-000000000002",
        "slug": "iroko",
        "name": "אירוקו פרקטים",
        "graph_type": "iroko",
        "llm_model": "anthropic/claude-sonnet-4-6",
        "qdrant_collection": "iroko_knowledge",
        "rate_limit_rpm": 60,
        "extra_config": {},
        "system_prompt_file": PROMPTS_DIR / "iroko" / "system_prompt.md",
    },
    "dng": {
        "id": "00000000-0000-0000-0000-000000000003",
        "slug": "dng",
        "name": "DNG Medical",
        "graph_type": "dng",
        "llm_model": "anthropic/claude-sonnet-4-6",
        "qdrant_collection": "dng_knowledge",
        "rate_limit_rpm": 60,
        "extra_config": {
            "consultation_fee_ils": 180,
            "payment_provider": "hyp",
        },
        "system_prompt_file": PROMPTS_DIR / "dng" / "system_prompt.md",
    },
}


# ─── Seeding logic ────────────────────────────────────────────────────────────


async def seed_tenant(slug: str, database_url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    config = TENANT_CONFIGS[slug]
    system_prompt = _read_prompt(config["system_prompt_file"])

    print(f"Seeding tenant: {slug} ({config['name']})")
    if system_prompt:
        print(f"  System prompt: {len(system_prompt)} chars")
    else:
        print("  System prompt: (empty — will use platform default)")

    engine = create_async_engine(database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        # Upsert via raw SQL for simplicity (works without Alembic run)
        await db.execute(
            text("""
                INSERT INTO tenants (id, slug, name, graph_type, system_prompt, llm_model,
                                     qdrant_collection, rate_limit_rpm, extra_config,
                                     is_active, created_at, updated_at)
                VALUES (:id, :slug, :name, :graph_type, :system_prompt, :llm_model,
                        :qdrant_collection, :rate_limit_rpm, CAST(:extra_config AS jsonb),
                        true, now(), now())
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    graph_type = EXCLUDED.graph_type,
                    system_prompt = EXCLUDED.system_prompt,
                    llm_model = EXCLUDED.llm_model,
                    qdrant_collection = EXCLUDED.qdrant_collection,
                    rate_limit_rpm = EXCLUDED.rate_limit_rpm,
                    extra_config = EXCLUDED.extra_config,
                    updated_at = now()
            """),
            {
                "id": config["id"],
                "slug": config["slug"],
                "name": config["name"],
                "graph_type": config["graph_type"],
                "system_prompt": system_prompt or None,
                "llm_model": config["llm_model"],
                "qdrant_collection": config["qdrant_collection"],
                "rate_limit_rpm": config["rate_limit_rpm"],
                "extra_config": str(config["extra_config"]).replace("'", '"'),
            },
        )

        channel_env_var = {
            "pashutomazia": "PASHUTOMAZIA_GREEN_API_TOKEN",
            "iroko": "IROKO_GREEN_API_TOKEN",
        }.get(slug)

        if channel_env_var:
            token = os.environ.get(channel_env_var, "")
            if not token:
                print(f"  WARNING: {channel_env_var} not set — token_ref will be empty")
            await db.execute(
                text("""
                    INSERT INTO tenant_channels (id, tenant_id, instance_id, token_ref, label, is_active, created_at, updated_at)
                    VALUES (gen_random_uuid(), :tenant_id, '7103335194', :token_ref, 'default', true, now(), now())
                    ON CONFLICT (instance_id) DO UPDATE SET
                        tenant_id = EXCLUDED.tenant_id,
                        token_ref = CASE WHEN EXCLUDED.token_ref <> '' THEN EXCLUDED.token_ref ELSE tenant_channels.token_ref END,
                        is_active = EXCLUDED.is_active,
                        updated_at = now()
                """),
                {"tenant_id": config["id"], "token_ref": token},
            )

        await db.commit()
        print(f"  ✓ Tenant '{slug}' upserted.")

    await engine.dispose()


async def main(tenants: list[str], database_url: str) -> None:
    for slug in tenants:
        if slug not in TENANT_CONFIGS:
            print(f"Unknown tenant: {slug}. Available: {list(TENANT_CONFIGS)}")
            continue
        await seed_tenant(slug, database_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed tenant records")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="Tenant slug to seed")
    group.add_argument("--all", action="store_true", help="Seed all tenants")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL environment variable is required")
        raise SystemExit(1)

    tenants_to_seed = list(TENANT_CONFIGS) if args.all else [args.tenant]
    asyncio.run(main(tenants_to_seed, db_url))
