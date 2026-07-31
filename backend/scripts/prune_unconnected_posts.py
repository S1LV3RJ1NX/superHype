"""Remove unconnected participants from campaigns that are in review or live.

Older campaigns were planned before the app required a connected account, so
their plans still carry posts for people who never connected LinkedIn (or X).
Those rows can never publish: this deletes the unpublished rows belonging to
users without a social account on the campaign's platform, plus the unpublished
likes/comments that target those rows, so the plan only contains people who can
actually act.

Run with:
    uv run python -m scripts.prune_unconnected_posts           # dry run
    uv run python -m scripts.prune_unconnected_posts --yes     # actually delete

Point it at another environment by exporting DATABASE_URL for the command
rather than editing .env, and read the banner it prints before passing --yes.

Guards, because this deletes campaign rows:
  - dry run unless --yes
  - only campaigns in review, publishing, or paused
  - only unpublished rows (pending, scheduled, action_required, failed) with no
    external_id; published, approved (mid-flight), and settled rows are never
    touched
  - a user with any account row on the platform counts as connected, including
    stale ones (they can reconnect); only people with no account at all are
    pruned
  - queued publish/notify jobs for the deleted rows are flushed from Redis
  - each touched campaign gets an audit row
"""

import argparse
import asyncio
import uuid
from collections import defaultdict
from urllib.parse import urlsplit

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.user import User
from app.repositories import audit_repo

CAMPAIGN_STATUSES = ("review", "publishing", "paused")
DELETABLE_POST_STATUSES = ("pending", "scheduled", "action_required", "failed")


def _safe_dsn() -> str:
    """Host and database only: the DSN carries a password."""
    parts = urlsplit(settings.DATABASE_URL)
    return f"{parts.hostname or '?'}{parts.path or ''}"


async def _connected_user_ids(db: AsyncSession, platform: str) -> set[uuid.UUID]:
    stmt = select(SocialAccount.user_id).where(SocialAccount.platform == platform)
    return set((await db.execute(stmt)).scalars())


async def _doomed_for_campaign(
    db: AsyncSession, campaign: Campaign
) -> tuple[list[Post], list[Post], set[uuid.UUID]]:
    """(rows by unconnected users, dependent rows targeting them, user ids)."""
    connected = await _connected_user_ids(db, campaign.platform)
    rows = list(
        (
            await db.execute(
                select(Post).where(
                    Post.campaign_id == campaign.id,
                    Post.status.in_(DELETABLE_POST_STATUSES),
                    Post.external_id.is_(None),
                )
            )
        ).scalars()
    )
    own = [p for p in rows if p.user_id not in connected]
    own_ids = {p.id for p in own}
    dependents = [
        p
        for p in rows
        if p.id not in own_ids
        and p.target_post_id is not None
        and p.target_post_id in own_ids
    ]
    return own, dependents, {p.user_id for p in own}


async def _flush_queue(post_ids: set[str]) -> int:
    from app.workers.queue import (
        close_arq_pool,
        flush_member_jobs_on_pool,
        get_arq_pool,
    )

    if not post_ids:
        return 0
    try:
        pool = await get_arq_pool()
    except Exception as exc:
        print(f"Warning: could not reach Redis to clear queued jobs ({exc}).")
        return 0
    try:
        return await flush_member_jobs_on_pool(
            pool, post_ids=post_ids, user_ids=set(), account_ids=set()
        )
    finally:
        await close_arq_pool()


async def prune(execute: bool) -> None:
    async with async_session_factory() as db:
        campaigns = list(
            (
                await db.execute(
                    select(Campaign)
                    .where(Campaign.status.in_(CAMPAIGN_STATUSES))
                    .order_by(Campaign.created_at)
                )
            ).scalars()
        )

        print(f"Database: {_safe_dsn()}  (env={settings.ENV})")
        print(
            f"{len(campaigns)} campaign(s) in {', '.join(CAMPAIGN_STATUSES)} to check."
        )

        doomed_all: list[Post] = []
        per_campaign: dict[uuid.UUID, dict] = {}
        affected_users: set[uuid.UUID] = set()

        for c in campaigns:
            own, dependents, user_ids = await _doomed_for_campaign(db, c)
            if not own:
                continue
            doomed_all.extend(own)
            doomed_all.extend(dependents)
            affected_users |= user_ids
            per_campaign[c.id] = {
                "campaign": c,
                "own": own,
                "dependents": dependents,
                "user_ids": user_ids,
            }

        if not per_campaign:
            print("Nothing to do: every participant is connected.")
            return

        emails = dict(
            (
                await db.execute(
                    select(User.id, User.email).where(User.id.in_(affected_users))
                )
            ).all()
        )

        print()
        for info in per_campaign.values():
            c = info["campaign"]
            by_action: dict[str, int] = defaultdict(int)
            for p in info["own"]:
                by_action[p.action] += 1
            actions = ", ".join(f"{n} {a}" for a, n in sorted(by_action.items()))
            print(f'"{c.title}" ({c.platform}, {c.status}):')
            for uid in sorted(info["user_ids"], key=lambda u: emails.get(u, "")):
                print(f"  {emails.get(uid, uid)} (no {c.platform} account)")
            print(
                f"  -> removing {len(info['own'])} row(s) ({actions}) "
                f"and {len(info['dependents'])} dependent interaction(s)."
            )

        doomed_ids = [p.id for p in doomed_all]
        print(
            f"\nTotal: {len(doomed_ids)} row(s) across {len(per_campaign)} campaign(s)."
        )

        if not execute:
            print("\nDry run. Re-run with --yes to actually delete.")
            return

        await db.execute(
            update(AuditLog)
            .where(AuditLog.post_id.in_(doomed_ids))
            .values(post_id=None)
        )
        # Break self references before the rows go (dependents of deleted rows
        # are deleted too, but a settled row may still point at a doomed one).
        await db.execute(
            update(Post)
            .where(Post.target_post_id.in_(doomed_ids))
            .values(target_post_id=None)
        )
        await db.execute(delete(Post).where(Post.id.in_(doomed_ids)))

        for info in per_campaign.values():
            c = info["campaign"]
            await audit_repo.record(
                db,
                actor_id=None,
                action="campaign_pruned_unconnected",
                campaign_id=c.id,
                detail={
                    "removed_posts": len(info["own"]),
                    "removed_dependents": len(info["dependents"]),
                    "users": sorted(emails.get(u, str(u)) for u in info["user_ids"]),
                },
            )
        await db.commit()

        flushed = await _flush_queue({str(p) for p in doomed_ids})
        print(
            f"\nDone. Deleted {len(doomed_ids)} row(s) and removed {flushed} "
            "queued job(s)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove unconnected participants from review/live campaigns."
    )
    parser.add_argument(
        "--yes", action="store_true", help="Actually delete (otherwise dry run)."
    )
    args = parser.parse_args()
    asyncio.run(prune(execute=args.yes))


if __name__ == "__main__":
    main()
