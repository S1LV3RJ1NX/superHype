"""Slack identity repository: maps app users to Slack users and DM channels.

The mapping is keyed by ``user_id`` (the primary key) and also looked up by
``slack_user_id`` when an inbound interaction tells us who clicked. Resolving an
identity is a one-time Slack lookup that we cache here, so later DMs skip the
round trip.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.slack_identity import SlackIdentity


class SlackIdentityRepository:
    async def get_by_user(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> SlackIdentity | None:
        return await db.get(SlackIdentity, user_id)

    async def get_by_slack_user(
        self, db: AsyncSession, slack_user_id: str
    ) -> SlackIdentity | None:
        stmt = select(SlackIdentity).where(SlackIdentity.slack_user_id == slack_user_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        slack_user_id: str,
        slack_dm_channel: str | None,
    ) -> SlackIdentity:
        identity = await db.get(SlackIdentity, user_id)
        if identity is None:
            identity = SlackIdentity(
                user_id=user_id,
                slack_user_id=slack_user_id,
                slack_dm_channel=slack_dm_channel,
            )
            db.add(identity)
        else:
            identity.slack_user_id = slack_user_id
            identity.slack_dm_channel = slack_dm_channel
        await db.flush()
        return identity


slack_identity_repo = SlackIdentityRepository()
