"""Reset one user's onboarding so they run through the flow again.

Run with:
    uv run python -m scripts.reset_onboarding                       # default admin
    uv run python -m scripts.reset_onboarding --email you@corp.com

Onboarding completion is signaled by two things: the user's team (Step 1) and a
connected LinkedIn account, which drives linkedin_status (Step 2). This clears
team_id and deletes the user's social account so the app's onboarding gate sends
them back to Step 1. The user row itself is kept (email, role, id), so this is
non-destructive apart from the LinkedIn connection, which is re-established by
reconnecting during onboarding.
"""

import argparse
import asyncio

from sqlalchemy import delete, select, update

from app.db.session import async_session_factory
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.user import User

DEFAULT_EMAIL = "prathamesh@truefoundry.com"


async def reset(email: str) -> None:
    async with async_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            print(f"No user with email {email!r}.")
            raise SystemExit(1)

        # posts.social_account_id references social_accounts with no ON DELETE, so
        # detach the user's posts from their account before removing it, otherwise
        # the delete fails for anyone who has already posted.
        await db.execute(
            update(Post).where(Post.user_id == user.id).values(social_account_id=None)
        )
        accounts = await db.execute(
            delete(SocialAccount).where(SocialAccount.user_id == user.id)
        )
        user.team_id = None
        await db.commit()

        print(
            f"Reset onboarding for {email}: cleared team, removed "
            f"{accounts.rowcount} LinkedIn account(s). "
            "Log in again to start at Step 1."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a user's onboarding state.")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    args = parser.parse_args()
    asyncio.run(reset(args.email))


if __name__ == "__main__":
    main()
