"""One-off: wipe all users (and campaigns) except a kept admin, for a fresh start.

Run with:
    uv run python -m scripts.wipe_users            # dry run: prints what it would do
    uv run python -m scripts.wipe_users --yes      # actually delete
    uv run python -m scripts.wipe_users --keep-email someone@corp.com --yes

Keeps exactly one user (default prathamesh@truefoundry.com) with their social
account and Slack identity intact, so they stay onboarded. Deletes every other
user and cascades their social accounts and Slack identities, and clears all
campaigns, posts, assets, and the audit log for a clean slate. Everyone else
re-onboards (team + LinkedIn) on their next login.

Destructive and not reversible. It targets whatever DATABASE_URL points at, so
double-check the environment before passing --yes. As a guard it refuses to run
if the keep-user is not present in the database (wrong DB or wrong email).
"""

import argparse
import asyncio

from sqlalchemy import delete, func, select

from app.db.session import async_session_factory
from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.slack_identity import SlackIdentity
from app.models.social_account import SocialAccount
from app.models.user import User

DEFAULT_KEEP_EMAIL = "prathamesh@truefoundry.com"


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def wipe(keep_email: str, execute: bool) -> None:
    async with async_session_factory() as db:
        keep = (
            await db.execute(select(User).where(User.email == keep_email))
        ).scalar_one_or_none()
        if keep is None:
            print(
                f"Abort: keep-user {keep_email!r} is not in this database. "
                "Refusing to wipe (wrong DB or wrong email?)."
            )
            raise SystemExit(1)

        users = await _count(db, User)
        campaigns = await _count(db, Campaign)
        posts = await _count(db, Post)

        print(
            f"Database has {users} user(s), {campaigns} campaign(s), {posts} post(s)."
        )
        print(
            f"Keeping {keep_email} ({keep.id}) with their social account and Slack "
            "identity."
        )
        print(
            f"Would delete {users - 1} other user(s), plus all campaigns, posts, "
            "assets, and audit log."
        )

        if not execute:
            print("\nDry run. Re-run with --yes to actually delete.")
            return

        # No ON DELETE cascade in the schema, so remove children before parents.
        await db.execute(delete(AuditLog))
        await db.execute(delete(Post))
        await db.execute(delete(Campaign))
        await db.execute(delete(Asset))
        await db.execute(delete(SocialAccount).where(SocialAccount.user_id != keep.id))
        await db.execute(delete(SlackIdentity).where(SlackIdentity.user_id != keep.id))
        result = await db.execute(delete(User).where(User.id != keep.id))
        await db.commit()

        print(
            f"\nDone. Deleted {result.rowcount} user(s); {keep_email} kept. "
            "Everyone else re-onboards on next login."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wipe users and campaigns except a kept admin."
    )
    parser.add_argument("--keep-email", default=DEFAULT_KEEP_EMAIL)
    parser.add_argument(
        "--yes", action="store_true", help="Actually delete (otherwise dry run)."
    )
    args = parser.parse_args()
    asyncio.run(wipe(args.keep_email, execute=args.yes))


if __name__ == "__main__":
    main()
