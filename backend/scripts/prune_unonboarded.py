"""Delete users who signed in with Google but never finished onboarding.

A users row is created the moment Google login succeeds, so anyone who opened
the app once and bailed out of the wizard sits in the roster forever with no
team and no LinkedIn. This removes them. They are recreated on their next login
and start onboarding from the top.

Run with:
    uv run python -m scripts.prune_unonboarded                 # dry run
    uv run python -m scripts.prune_unonboarded --yes           # actually delete
    uv run python -m scripts.prune_unonboarded --keep-email a@corp.com --yes

Point it at another environment by exporting DATABASE_URL for the command
rather than editing .env, and read the banner it prints before passing --yes.

Guards, because this is destructive and not reversible:
  - dry run unless --yes
  - refuses to touch anyone who has a published post (external_id set)
  - refuses to delete the last remaining admin
  - --keep-email (repeatable) protects specific accounts

Deleting a user cascades by hand, since the schema has no ON DELETE on the user
foreign keys: their unpublished posts and any unpublished posts targeting those
go, along with their social accounts and Slack identity. References that are
nullable (audit actor, campaign creator, asset uploader, content rule editor)
are set to null so the history and the campaigns survive.
"""

import argparse
import asyncio
import uuid
from urllib.parse import urlsplit

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.content_rule import ContentRule
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.social_account import SocialAccount
from app.models.user import User


def _safe_dsn() -> str:
    """Host and database only: the DSN carries a password."""
    parts = urlsplit(settings.DATABASE_URL)
    return f"{parts.hostname or '?'}{parts.path or ''}"


async def _find_unonboarded(db: AsyncSession, keep: set[str]) -> list[User]:
    """Users missing a team or a LinkedIn account, matching the app's own gate."""
    connected = select(SocialAccount.user_id).where(
        SocialAccount.platform == "linkedin"
    )
    stmt = (
        select(User)
        .where(or_(User.team_id.is_(None), User.id.not_in(connected)))
        .order_by(User.created_at)
    )
    users = list((await db.execute(stmt)).scalars())
    return [u for u in users if u.email.lower() not in keep]


async def _published_posts(db: AsyncSession, post_ids: list[uuid.UUID]) -> list[Post]:
    if not post_ids:
        return []
    stmt = select(Post).where(Post.id.in_(post_ids), Post.external_id.is_not(None))
    return list((await db.execute(stmt)).scalars())


def _describe(user: User, connected: set[uuid.UUID]) -> str:
    missing = []
    if user.team_id is None:
        missing.append("no team")
    if user.id not in connected:
        missing.append("no LinkedIn")
    return f"{user.email} ({user.role}, {' + '.join(missing)})"


async def _flush_queue(
    *, post_ids: set[str], user_ids: set[str], account_ids: set[str]
) -> int:
    from app.workers.queue import (
        close_arq_pool,
        flush_member_jobs_on_pool,
        get_arq_pool,
    )

    try:
        pool = await get_arq_pool()
    except Exception as exc:
        print(f"Warning: could not reach Redis to clear queued jobs ({exc}).")
        return 0
    try:
        return await flush_member_jobs_on_pool(
            pool, post_ids=post_ids, user_ids=user_ids, account_ids=account_ids
        )
    finally:
        await close_arq_pool()


async def prune(keep_emails: list[str], execute: bool) -> None:
    keep = {e.strip().lower() for e in keep_emails if e.strip()}

    async with async_session_factory() as db:
        total_users = await db.scalar(select(func.count()).select_from(User)) or 0
        targets = await _find_unonboarded(db, keep)

        print(f"Database: {_safe_dsn()}  (env={settings.ENV})")
        print(f"{total_users} user(s) total, {len(targets)} not onboarded.")
        if keep:
            print(f"Protected by --keep-email: {', '.join(sorted(keep))}")
        if not targets:
            print("Nothing to do.")
            return

        target_ids = [u.id for u in targets]

        admins_total = (
            await db.scalar(
                select(func.count()).select_from(User).where(User.role == "admin")
            )
            or 0
        )
        admins_hit = sum(1 for u in targets if u.role == "admin")
        if admins_hit and admins_hit >= admins_total:
            print(
                f"\nAbort: this would delete all {admins_total} admin(s). "
                "Protect one with --keep-email."
            )
            raise SystemExit(1)

        own_posts = list(
            (
                await db.execute(select(Post.id).where(Post.user_id.in_(target_ids)))
            ).scalars()
        )
        dependents: list[uuid.UUID] = []
        if own_posts:
            dependents = list(
                (
                    await db.execute(
                        select(Post.id).where(
                            Post.target_post_id.in_(own_posts),
                            Post.id.not_in(own_posts),
                        )
                    )
                ).scalars()
            )
        doomed_posts = own_posts + dependents

        published = await _published_posts(db, doomed_posts)
        if published:
            print(f"\nAbort: {len(published)} post(s) in scope are already published.")
            for p in published[:10]:
                print(f"  post {p.id} ({p.action}) external_id={p.external_id}")
            print("Someone here has posted for real. Resolve by hand.")
            raise SystemExit(1)

        connected = set(
            (
                await db.execute(
                    select(SocialAccount.user_id).where(
                        SocialAccount.platform == "linkedin"
                    )
                )
            ).scalars()
        )
        # Captured before the rows go, since the queue cleanup keys off them.
        account_ids = {
            str(a)
            for a in (
                await db.execute(
                    select(SocialAccount.id).where(
                        SocialAccount.user_id.in_(target_ids)
                    )
                )
            ).scalars()
        }
        print("\nWould delete:")
        for u in targets:
            print(f"  {_describe(u, connected)}")

        print(
            f"\nPlus {len(own_posts)} of their post(s) and {len(dependents)} "
            "dependent post(s), their social accounts and Slack identities. "
            "Audit rows, campaigns, assets, and content rules are kept with the "
            "reference nulled."
        )
        if doomed_posts:
            breakdown = await db.execute(
                select(Post.status, Post.action, func.count())
                .where(Post.id.in_(doomed_posts))
                .group_by(Post.status, Post.action)
                .order_by(Post.status, Post.action)
            )
            print("  post breakdown:")
            for status, action, count in breakdown:
                print(f"    {status} {action}: {count}")
        print(
            "Any deferred publish, notify, or reconnect job these people still "
            "have in Redis is dropped too, so nothing wakes up pointing at a "
            "deleted row."
        )

        if not execute:
            print("\nDry run. Re-run with --yes to actually delete.")
            return

        if doomed_posts:
            await db.execute(
                update(AuditLog)
                .where(AuditLog.post_id.in_(doomed_posts))
                .values(post_id=None)
            )
            # Break the self reference before the rows go, in either direction.
            await db.execute(
                update(Post)
                .where(Post.target_post_id.in_(doomed_posts))
                .values(target_post_id=None)
            )
            await db.execute(delete(Post).where(Post.id.in_(doomed_posts)))

        await db.execute(
            update(AuditLog)
            .where(AuditLog.actor_id.in_(target_ids))
            .values(actor_id=None)
        )
        await db.execute(
            update(Campaign)
            .where(Campaign.created_by.in_(target_ids))
            .values(created_by=None)
        )
        await db.execute(
            update(Campaign)
            .where(Campaign.launched_by.in_(target_ids))
            .values(launched_by=None)
        )
        await db.execute(
            update(Asset)
            .where(Asset.created_by.in_(target_ids))
            .values(created_by=None)
        )
        await db.execute(
            update(ContentRule)
            .where(ContentRule.updated_by.in_(target_ids))
            .values(updated_by=None)
        )
        await db.execute(
            delete(SlackIdentity).where(SlackIdentity.user_id.in_(target_ids))
        )
        await db.execute(
            delete(SocialAccount).where(SocialAccount.user_id.in_(target_ids))
        )
        await db.execute(delete(User).where(User.id.in_(target_ids)))
        await db.commit()

        # Redis outlives the rows, so a deferred publish or reminder would wake
        # up pointing at a user and post that are gone. Drop those first.
        flushed = await _flush_queue(
            post_ids={str(p) for p in doomed_posts},
            user_ids={str(u) for u in target_ids},
            account_ids=account_ids,
        )

        print(
            f"\nDone. Deleted {len(target_ids)} user(s) and removed {flushed} "
            "queued job(s). They are recreated on their next login and start "
            "onboarding from Step 1."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete users who never finished onboarding."
    )
    parser.add_argument(
        "--keep-email",
        action="append",
        default=[],
        help="Protect this account (repeatable).",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Actually delete (otherwise dry run)."
    )
    args = parser.parse_args()
    asyncio.run(prune(args.keep_email, execute=args.yes))


if __name__ == "__main__":
    main()
