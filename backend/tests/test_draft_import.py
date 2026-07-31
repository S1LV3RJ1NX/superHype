"""Spreadsheet draft import: template, parsing, matching, plan overlay, badges.

Covers the parser (xlsx and csv, header tolerance, URL-only post cells), the
roster matching rules (email first, unique name fallback), the template and
preview endpoints, the manual-draft overlay in build_plan (manual rows never
hit the gateway), survival across regenerate, and the source flip on edit.
"""

import io
import uuid

import pytest
from openpyxl import Workbook, load_workbook

from app.models.campaign import Campaign
from app.models.user import User
from app.schemas.post import ManualDraft
from app.services import campaign_service, draft_import_service
from app.services.draft_import_service import (
    DraftSheetError,
    build_template,
    parse_sheet,
)

pytestmark = pytest.mark.asyncio


def _csv(text: str) -> bytes:
    return text.encode()


def _xlsx(rows: list[list[str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _user(db, *, email: str, name: str | None = None, role="viewer") -> User:
    u = User(email=email, name=name, role=role, is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _campaign(db, *, ctype="distribute", **kw) -> Campaign:
    c = Campaign(title="C", type=ctype, status="draft", **kw)
    db.add(c)
    await db.flush()
    return c


# ---------------------------------------------------------------- parsing


async def test_template_roundtrips_through_parser():
    rows = parse_sheet(build_template(), "super-hype-drafts.xlsx")
    assert len(rows) == 1
    r = rows[0]
    assert r.email == "jane@example.com"
    assert r.name == "Jane Doe"
    assert r.draft.post_body and "shipped" in r.draft.post_body
    assert r.draft.self_comment == "Link in the comments!"
    assert len(r.draft.comments) == 2


async def test_csv_headers_matched_case_and_whitespace_insensitively():
    data = _csv(
        "Email ,NAME,Post,Self Comment,Comment 1,comment_2,Notes\n"
        'a@corp.com,Alice,"Hello, world",follow me,nice one,great,ignored\n'
    )
    rows = parse_sheet(data, "drafts.csv")
    assert len(rows) == 1
    r = rows[0]
    assert r.email == "a@corp.com"
    assert r.draft.post_body == "Hello, world"  # quoted comma survives
    assert r.draft.self_comment == "follow me"
    assert r.draft.comments == ["nice one", "great"]


async def test_xlsx_upload_parses_first_sheet():
    data = _xlsx(
        [
            ["email", "name", "post", "self_comment", "comment_1"],
            ["b@corp.com", "Bob", "my post", "", "good stuff"],
        ]
    )
    rows = parse_sheet(data, "drafts.xlsx")
    assert len(rows) == 1
    assert rows[0].draft.post_body == "my post"
    assert rows[0].draft.self_comment is None
    assert rows[0].draft.comments == ["good stuff"]


async def test_url_only_post_cell_is_treated_as_blank_with_warning():
    data = _csv(
        "email,post\na@corp.com,https://example.com/tracker-link\n",
    )
    rows = parse_sheet(data, "d.csv")
    assert rows[0].draft.post_body is None
    assert any("URL" in w for w in rows[0].warnings)


async def test_fully_blank_rows_are_skipped():
    data = _csv("email,name,post\na@corp.com,Alice,hi\n,,\n , , \n")
    rows = parse_sheet(data, "d.csv")
    assert len(rows) == 1


async def test_rejects_unknown_extension():
    with pytest.raises(DraftSheetError, match=r"\.xlsx or \.csv"):
        parse_sheet(b"whatever", "drafts.numbers")


async def test_rejects_oversized_file():
    big = b"x" * (draft_import_service.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(DraftSheetError, match="too large"):
        parse_sheet(big, "d.csv")


async def test_rejects_sheet_without_usable_headers():
    data = _csv("foo,bar\n1,2\n")
    with pytest.raises(DraftSheetError, match="sample template"):
        parse_sheet(data, "d.csv")


async def test_rejects_corrupt_xlsx():
    with pytest.raises(DraftSheetError, match="xlsx"):
        parse_sheet(b"not a zip archive", "d.xlsx")


# ---------------------------------------------------------------- matching


async def test_match_by_email_is_case_insensitive(db):
    alice = await _user(db, email="alice@corp.com", name="Alice Adams")
    rows = parse_sheet(_csv("email,post\nALICE@CORP.COM,hello\n"), "d.csv")
    preview = await draft_import_service.match_rows(db, rows)
    assert [m.user_id for m in preview.matched] == [alice.id]
    assert preview.matched[0].matched_by == "email"
    assert preview.unmatched == []


async def test_name_fallback_requires_unique_match(db):
    bob = await _user(db, email="bob@corp.com", name="Bob B")
    await _user(db, email="carol1@corp.com", name="Carol C")
    await _user(db, email="carol2@corp.com", name="Carol C")

    data = _csv("email,name,post\n,bob b,post one\n,Carol C,post two\n")
    preview = await draft_import_service.match_rows(db, parse_sheet(data, "d.csv"))

    assert [m.user_id for m in preview.matched] == [bob.id]
    assert preview.matched[0].matched_by == "name"
    assert len(preview.unmatched) == 1
    assert "More than one user" in preview.unmatched[0].reason


async def test_unknown_email_is_unmatched_not_name_matched(db):
    # An email that misses stays unmatched even if the name would match: a wrong
    # email is a mistake to surface, not something to silently paper over.
    await _user(db, email="dana@corp.com", name="Dana D")
    data = _csv("email,name,post\nwrong@corp.com,Dana D,hi\n")
    preview = await draft_import_service.match_rows(db, parse_sheet(data, "d.csv"))
    assert preview.matched == []
    assert "No user with email" in preview.unmatched[0].reason


async def test_duplicate_person_second_row_unmatched(db):
    await _user(db, email="eve@corp.com", name="Eve E")
    data = _csv("email,post\neve@corp.com,first\neve@corp.com,second\n")
    preview = await draft_import_service.match_rows(db, parse_sheet(data, "d.csv"))
    assert len(preview.matched) == 1
    assert len(preview.unmatched) == 1
    assert "earlier row" in preview.unmatched[0].reason


# ---------------------------------------------------------------- endpoints


async def test_template_endpoint_streams_xlsx_for_editor(client, as_role):
    async with as_role("editor"):
        resp = await client.get("/v1/campaigns/drafts/template")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    assert "super-hype-drafts.xlsx" in resp.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(resp.content))
    header = [c.value for c in next(wb.worksheets[0].iter_rows(max_row=1))]
    assert header[:4] == ["email", "name", "post", "self_comment"]


async def test_template_endpoint_rejects_viewer(client, as_role):
    async with as_role("viewer"):
        resp = await client.get("/v1/campaigns/drafts/template")
    assert resp.status_code == 403


async def test_preview_endpoint_matches_roster(client, as_role, db):
    await _user(db, email="fred@corp.com", name="Fred F")
    await db.commit()
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json={"title": "D", "type": "distribute", "seed_content": "seed"},
        )
        cid = created.json()["id"]
        data = _csv("email,post,comment_1\nfred@corp.com,my post,nice\n")
        resp = await client.post(
            f"/v1/campaigns/{cid}/drafts/preview",
            files={"file": ("drafts.csv", data, "text/csv")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["matched"]) == 1
    assert body["matched"][0]["user_email"] == "fred@corp.com"
    assert body["matched"][0]["draft"]["post_body"] == "my post"
    assert body["matched"][0]["draft"]["comments"] == ["nice"]
    assert body["unmatched"] == []


async def test_preview_endpoint_rejects_amplify(client, as_role):
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json={
                "title": "A",
                "type": "amplify",
                "seed_url": (
                    "https://www.linkedin.com/feed/update/"
                    "urn:li:activity:7123456789012345678/"
                ),
                "seed_content": "x",
            },
        )
        cid = created.json()["id"]
        resp = await client.post(
            f"/v1/campaigns/{cid}/drafts/preview",
            files={"file": ("d.csv", b"email,post\na@b.c,hi\n", "text/csv")},
        )
    assert resp.status_code == 409


async def test_preview_endpoint_rejects_non_creator(client, as_role):
    async with as_role("editor", email="creator@test.local"):
        created = await client.post(
            "/v1/campaigns",
            json={"title": "D", "type": "distribute", "seed_content": "seed"},
        )
        cid = created.json()["id"]
    async with as_role("editor", email="other@test.local"):
        resp = await client.post(
            f"/v1/campaigns/{cid}/drafts/preview",
            files={"file": ("d.csv", b"email,post\na@b.c,hi\n", "text/csv")},
        )
    assert resp.status_code == 403


async def test_preview_endpoint_rejects_bad_file(client, as_role):
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json={"title": "D", "type": "distribute", "seed_content": "seed"},
        )
        cid = created.json()["id"]
        resp = await client.post(
            f"/v1/campaigns/{cid}/drafts/preview",
            files={"file": ("d.txt", b"email,post\na@b.c,hi\n", "text/plain")},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------- plan overlay


async def _distribute_pair(db):
    a = await _user(db, email=f"{uuid.uuid4().hex}@corp.com", name="A")
    b = await _user(db, email=f"{uuid.uuid4().hex}@corp.com", name="B")
    c = await _campaign(
        db, ctype="distribute", seed_content="seed", self_comment="campaign sc"
    )
    return a, b, c


async def test_overlay_prefills_post_comments_and_self_comment(db):
    a, b, c = await _distribute_pair(db)
    assignments = await campaign_service.expand_participants(db, c, [a.id, b.id])
    campaign_service.apply_manual_drafts(
        assignments,
        {
            a.id: ManualDraft(
                post_body="A's own post",
                self_comment="A's link comment",
                comments=["A comments on B"],
            )
        },
    )

    rows = await campaign_service.build_plan(db, c.id, assignments, generate=False)

    by_action_user = {(p.action, p.user_id): p for p in rows}
    a_post = by_action_user[("post", a.id)]
    assert a_post.body == "A's own post"
    assert a_post.source == "manual"
    # B provided nothing: empty body, still marked ai.
    assert by_action_user[("post", b.id)].source == "ai"

    a_comment = by_action_user[("comment", a.id)]
    assert a_comment.body == "A comments on B"
    assert a_comment.source == "manual"
    assert by_action_user[("comment", b.id)].source == "ai"

    a_sc = by_action_user[("self_comment", a.id)]
    assert a_sc.body == "A's link comment"
    assert a_sc.source == "manual"
    # B falls back to the campaign-level self comment.
    assert by_action_user[("self_comment", b.id)].body == "campaign sc"


async def test_manual_rows_never_hit_the_gateway(db, monkeypatch):
    a, b, c = await _distribute_pair(db)

    generated_users: list[int] = []

    async def fake_variations(seed, n, **kw):
        generated_users.append(n)
        return [f"gen-post-{i}" for i in range(n)]

    comment_items: list[dict] = []

    async def fake_interactions(target_text, items, **kw):
        comment_items.extend(i for i in items if i["action"] == "comment")
        return [f"gen-{i['action']}" for i in items]

    monkeypatch.setattr(campaign_service, "generate_variations", fake_variations)
    monkeypatch.setattr(campaign_service, "generate_interactions", fake_interactions)

    assignments = await campaign_service.expand_participants(db, c, [a.id, b.id])
    campaign_service.apply_manual_drafts(
        assignments,
        {a.id: ManualDraft(post_body="A manual post", comments=["A manual comment"])},
    )
    rows = await campaign_service.build_plan(db, c.id, assignments, generate=True)

    # Only B's post was generated; A's manual body and comment were kept.
    assert generated_users == [1]
    assert len(comment_items) == 1  # only B's comment on A
    by_action_user = {(p.action, p.user_id): p for p in rows}
    assert by_action_user[("post", a.id)].body == "A manual post"
    assert by_action_user[("post", a.id)].source == "manual"
    assert by_action_user[("post", b.id)].body == "gen-post-0"
    assert by_action_user[("post", b.id)].source == "ai"
    assert by_action_user[("comment", a.id)].body == "A manual comment"
    assert by_action_user[("comment", a.id)].source == "manual"
    assert by_action_user[("comment", b.id)].body == "gen-comment"
    assert by_action_user[("comment", b.id)].source == "ai"


async def test_comment_pool_exhaustion_falls_back_to_ai(db):
    a = await _user(db, email=f"{uuid.uuid4().hex}@corp.com")
    b = await _user(db, email=f"{uuid.uuid4().hex}@corp.com")
    d = await _user(db, email=f"{uuid.uuid4().hex}@corp.com")
    c = await _campaign(db, ctype="distribute", seed_content="seed")

    assignments = await campaign_service.expand_participants(db, c, [a.id, b.id, d.id])
    campaign_service.apply_manual_drafts(
        assignments, {a.id: ManualDraft(comments=["only one comment"])}
    )

    a_comments = [x for x in assignments if x.action == "comment" and x.user_id == a.id]
    assert len(a_comments) == 2  # A comments on B and D
    assert a_comments[0].body == "only one comment"
    assert a_comments[0].source == "manual"
    assert a_comments[1].body is None
    assert a_comments[1].source == "ai"


async def test_manual_rows_survive_regenerate(db, monkeypatch):
    a, b, c = await _distribute_pair(db)
    generation = {"round": 1}

    async def fake_variations(seed, n, **kw):
        return [f"gen{generation['round']}-post-{i}" for i in range(n)]

    async def fake_interactions(target_text, items, **kw):
        return [f"gen{generation['round']}-{i['action']}" for i in items]

    monkeypatch.setattr(campaign_service, "generate_variations", fake_variations)
    monkeypatch.setattr(campaign_service, "generate_interactions", fake_interactions)

    assignments = await campaign_service.expand_participants(db, c, [a.id, b.id])
    campaign_service.apply_manual_drafts(
        assignments, {a.id: ManualDraft(post_body="A manual post")}
    )
    await campaign_service.build_plan(db, c.id, assignments, generate=True)

    # Regenerate: fresh assignments (no drafts resent), round 2 texts.
    generation["round"] = 2
    fresh = await campaign_service.expand_participants(db, c, [a.id, b.id])
    rows = await campaign_service.build_plan(
        db, c.id, fresh, generate=True, regenerate=True
    )

    by_action_user = {(p.action, p.user_id): p for p in rows}
    # The manual post outlives regenerate; AI text is rewritten.
    assert by_action_user[("post", a.id)].body == "A manual post"
    assert by_action_user[("post", a.id)].source == "manual"
    assert by_action_user[("post", b.id)].body == "gen2-post-0"


async def test_replan_without_drafts_keeps_manual_rows(db):
    a, b, c = await _distribute_pair(db)
    assignments = await campaign_service.expand_participants(db, c, [a.id, b.id])
    campaign_service.apply_manual_drafts(
        assignments, {a.id: ManualDraft(post_body="A manual post")}
    )
    await campaign_service.build_plan(db, c.id, assignments, generate=False)

    fresh = await campaign_service.expand_participants(db, c, [a.id, b.id])
    rows = await campaign_service.build_plan(db, c.id, fresh, generate=False)

    a_post = next(p for p in rows if p.action == "post" and p.user_id == a.id)
    assert a_post.body == "A manual post"
    assert a_post.source == "manual"


# ---------------------------------------------------------------- source on edit


async def test_editing_body_flips_source_to_manual(client, as_role):
    async with as_role("editor") as user:
        created = await client.post(
            "/v1/campaigns",
            json={
                "title": "A",
                "type": "amplify",
                "seed_url": (
                    "https://www.linkedin.com/feed/update/"
                    "urn:li:activity:7123456789012345678/"
                ),
                "seed_content": "x",
            },
        )
        cid = created.json()["id"]
        await client.post(
            f"/v1/campaigns/{cid}/plan", json={"participant_ids": [str(user.id)]}
        )
        posts = await client.get(f"/v1/campaigns/{cid}/posts")
        post = next(p for p in posts.json()["items"] if p["action"] == "comment")
        assert post["source"] == "ai"

        edited = await client.patch(
            f"/v1/posts/{post['id']}", json={"body": "hand-written"}
        )
    assert edited.status_code == 200
    assert edited.json()["source"] == "manual"
