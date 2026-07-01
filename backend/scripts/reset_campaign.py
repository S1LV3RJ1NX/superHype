"""Reset a campaign to its just-planned state so it can be launched again.

Run with:
    uv run python -m scripts.reset_campaign <campaign_id>
    uv run python -m scripts.reset_campaign <campaign_id> --regenerate
    uv run python -m scripts.reset_campaign                 # lists recent campaigns

Local-dev only. Moves the campaign back to ``review`` (clears ``launched_at``)
and rewinds every one of its posts to ``pending``, wiping the publish artifacts
(external ids, timestamps, engagement links, errors, retries, per-author media
urns). That lets you re-run the launch -> approve -> publish loop on an existing
campaign instead of creating a new one each time, which is handy for exercising
the distribute flow repeatedly.

By default the plan itself is untouched (the post rows and their bodies stay).
With ``--regenerate`` the plan is rebuilt from scratch through the LLM gateway,
reusing the current participants (the distinct authors of the existing posts).
Use this to pick up plan changes, e.g. a self-comment row added after the
campaign was first planned. Regeneration calls the LLM gateway synchronously, so
it does not need the worker running.

It never deletes a campaign. Flush the worker queue too if stale jobs might still
be deferred: ``make flush``.
"""

import argparse
import asyncio
import uuid

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.services import campaign_service
from app.services.generation_service import GenerationError


async def _list_recent() -> None:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(Campaign).order_by(Campaign.created_at.desc()).limit(20)
            )
        ).scalars()
        print("Recent campaigns (pass an id to reset one):\n")
        for c in rows:
            print(f"  {c.id}  [{c.type:10} {c.status:10}] {c.title}")


async def _rewind_posts(db, campaign_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Post)
        .where(Post.campaign_id == campaign_id)
        .values(
            status="pending",
            external_id=None,
            published_at=None,
            scheduled_at=None,
            first_comment_external_id=None,
            engagement_url=None,
            acknowledged_at=None,
            image_asset_urn=None,
            error=None,
            retries=0,
        )
    )
    return result.rowcount


async def reset(campaign_id: uuid.UUID, regenerate: bool) -> None:
    async with async_session_factory() as db:
        campaign = await db.get(Campaign, campaign_id)
        if campaign is None:
            print(f"No campaign with id {campaign_id}.")
            return

        # Participants = the distinct authors of the current plan. Captured before
        # any rebuild so --regenerate re-runs with the same people.
        participant_ids = list(
            (
                await db.execute(
                    select(Post.user_id)
                    .where(Post.campaign_id == campaign_id)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

        # Rewind rows to pending and the campaign back to review. For a rebuild
        # this also makes every row pending so build_plan clears them all (it only
        # deletes pending rows) before recreating the fresh plan.
        rewound = await _rewind_posts(db, campaign_id)
        campaign.status = "review"
        campaign.launched_at = None
        await db.commit()

        if not regenerate:
            print(
                f"Reset '{campaign.title}' ({campaign.type}) to review; "
                f"{rewound} posts back to pending. Launch it again to re-run."
            )
            return

        if not participant_ids:
            print(
                f"Reset '{campaign.title}' to review, but it has no participants "
                "to regenerate from. Build the plan from the UI first."
            )
            return

        # A rebuild hard-deletes the pending post rows, but audit_log rows from a
        # prior run still reference them (fk_audit_log_post_id_posts). Detach those
        # references (post_id is nullable) so the delete succeeds; the audit trail
        # stays, still linked to the campaign.
        await db.execute(
            update(AuditLog)
            .where(
                AuditLog.post_id.in_(
                    select(Post.id).where(Post.campaign_id == campaign_id)
                )
            )
            .values(post_id=None)
        )

        assignments = await campaign_service.expand_participants(
            db, campaign, participant_ids
        )
        try:
            rows = await campaign_service.build_plan(
                db,
                campaign_id,
                assignments,
                generate=True,
                actor_id=campaign.created_by,
            )
            await db.commit()
        except GenerationError as exc:
            await db.rollback()
            print(f"Regeneration failed at the LLM gateway: {exc}")
            raise SystemExit(1) from exc

        print(
            f"Regenerated '{campaign.title}' ({campaign.type}) in review: "
            f"{len(rows)} posts for {len(participant_ids)} participant(s). "
            "Launch it to re-run."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a campaign for local re-runs.")
    parser.add_argument(
        "campaign_id", nargs="?", help="Campaign id to reset (omit to list recent)."
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Rebuild the plan through the LLM gateway (reuses current participants).",
    )
    args = parser.parse_args()

    if not args.campaign_id:
        asyncio.run(_list_recent())
        return
    try:
        campaign_id = uuid.UUID(args.campaign_id)
    except ValueError:
        print(f"Not a valid campaign id: {args.campaign_id!r}")
        raise SystemExit(1) from None
    asyncio.run(reset(campaign_id, regenerate=args.regenerate))


if __name__ == "__main__":
    main()
