# Applying for the LinkedIn Community Management API

Why this matters for super-hype, how to apply, and an honest read on whether our
use case clears LinkedIn's vetting.

## Why we need it

Our token currently holds `w_member_social` and `r_basicprofile` only. That is
enough to publish and reshare on behalf of a member (the `POST /rest/posts`
path), which is why "repost thought" works. It is not enough to comment or like.

Comments and likes go through the `socialActions` API, which requires the
`w_member_social_feed` member scope. That scope is granted only through the
Community Management API, which is a vetted product, not self-serve.

While we wait for approval, comments and likes run **assisted-manual** rather
than failing: the `COMMUNITY_MANAGEMENT_ENABLED` setting defaults to false, so
the worker never calls the `socialActions` API. Instead it resolves the target
post, deep-links the person to it (with the suggested comment text), and the
person comments or likes in their own browser, then marks it done. The whole
product therefore runs today on a self-serve Share-on-LinkedIn app
(`w_member_social`). The day Community Management access lands, set
`COMMUNITY_MANAGEMENT_ENABLED=true` and comments and likes dispatch through the
API automatically, with no code change.

Scope to capability mapping:

| Action in our app | LinkedIn endpoint | Scope needed | Status today |
| --- | --- | --- | --- |
| post / reshare ("repost thought") | `POST /rest/posts` | `w_member_social` | works |
| comment | `POST /rest/socialActions/{urn}/comments` | `w_member_social_feed` | assisted-manual until approved |
| like | `POST /rest/socialActions/{urn}/likes` | `w_member_social_feed` | assisted-manual until approved |

## Eligibility and prerequisites

The Community Management API is "only available to registered legal
organizations for commercial use cases." Before applying, have ready:

1. A LinkedIn Page for the organization (personal profiles do not qualify).
2. A developer app in the Developer Portal.
3. App verification by the Page: a super admin of the associated LinkedIn Page
   must associate the app with the Page.
4. A verified business email (personal email addresses fail vetting).
5. The organization's legal name, registered address, website, and a valid
   privacy policy.

## Important constraint: a dedicated app

The Community Management API must be the only product on the developer app. If
the app already has Sign In, Share, or Ads products (or pending requests), the
request button is grayed out. The supported workaround is to create a new app on
the same company Page that has only the Community Management API on it, and use
that app for the request. The extra app is for verification and can be discarded
after approval.

## How to apply

1. In the Developer Portal, open the app, go to the Products tab, and request
   Community Management API (the increasing-access flow).
2. Complete the access request form / vetting survey. You have 21 days to submit
   it or the request is closed.
3. Development tier review checks: approved use case, verified business email,
   verified organization, verified website and domain, and app verified by the
   associated LinkedIn Page. Approval grants limited call volume.
4. Standard tier (full access): from My Apps then Products, submit the Standard
   tier form, plus a downloadable high-resolution screen recording that
   demonstrates all core functionality, a valid privacy policy, and compliance
   with the data storage requirements.

### Standard tier screencast (employee advocacy track)

The reviewer expects the recording to show:

1. A user approving access via the full OAuth flow.
2. A user posting to their LinkedIn profile via the app.
3. How a comment on that post by another member is displayed in the app.
4. What personal data fields from the commenter's profile are displayed.
5. How aggregate engagement on the post is displayed.
6. Any other core functionality that uses member personal data.

If the app does not include some of these (we are outbound-first and do not yet
display others' comments or engagement), the guidance is to say so explicitly in
the recording.

## Restrictions that apply to us

- No social feed use case: we may not render a feed of LinkedIn updates on a
  website or intranet. We do not, so this is fine.
- No advertising, sales, or recruiting use of member data. We do not, so fine.
- No fake or headless accounts; one profile may not manage many customers. We
  act only as the consenting member, so fine.
- Data storage limits: member social activity data may be stored for at most 48
  hours, and most member profile data for at most 24 hours. See the open risks
  below.

## Developer AI Policy alignment

This is the part that matters most for us, because we generate content. The
policy's required design principles say, in effect:

- Do not auto-publish AI-generated content to LinkedIn without end-user
  involvement.
- If generated content is attributed to the end user, give them tools to edit it
  first.
- Provide a channel for user feedback.

Our design already matches this: launch is compulsory, each member approves their
own item, and they can edit the generated text before it publishes. That
human-in-the-loop, edit-before-publish flow is exactly what the policy asks for
and is a strong point in our favor.

The policy also restricts using LinkedIn data obtained via the Marketing APIs as
an input or prompt to AI. Content created by our own consenting users may be used
as an input and even to create content. Content created by members who are not
users of our app may be used as a prompt only for narrow cases (prioritization,
sentiment, categorization), and using it to create or modify content is
prohibited.

## Will our use case be blocked?

Short answer: the core use case is supported and should pass, but a personal
proof of concept will not, and two design details need attention.

What is in our favor:

- Employee Advocacy (employees resharing and amplifying content via their own
  profiles) is a named, approved Community Management use case.
- Our edit-before-publish, per-person approval flow satisfies the Developer AI
  Policy's design principles for AI-generated content.

What can block or delay us:

1. Organization requirement. We must apply as a registered legal organization
   with a verified business email, domain, website, privacy policy, and a Page
   that verifies the app. A personal or hobby PoC will be rejected. This is the
   most likely reason to be blocked.
2. AI generation on other people's posts. Generating a comment from another
   member's post content can conflict with the AI policy's ban on creating
   content from non-user data. We are safe when amplifying the app user's own
   post (our main case) or when the user pastes the text themselves rather than
   us pulling it from the API. Generating comments off a third party's post from
   API-sourced text is the risky path.
3. Data retention. The 24-hour profile and 48-hour social-activity storage limits
   mean we cannot cache member profile fields (for example a connected account's
   display name) indefinitely, and we should not persist fetched member content
   beyond the window. Our current model stores `display_name` on the social
   account; that needs a retention story before a Standard tier review.

Net: apply as the company (not as an individual), keep AI generation scoped to
the user's own or user-pasted content, and add a data-retention story. With those
in place, the employee-advocacy use case is the kind LinkedIn approves.

## Links

- Increasing access (apply): https://learn.microsoft.com/linkedin/marketing/increasing-access
- Application review, tiers, screencast: https://learn.microsoft.com/linkedin/marketing/community-management-app-review
- Quick start (step 1, apply): https://learn.microsoft.com/linkedin/marketing/quick-start
- Community Management overview and approved use cases: https://learn.microsoft.com/linkedin/marketing/community-management/community-management-overview
- Restricted use cases: https://learn.microsoft.com/linkedin/marketing/restricted-use-cases
- Developer AI Policy: https://learn.microsoft.com/linkedin/marketing/developer-ai-policy
- Data storage requirements: https://learn.microsoft.com/linkedin/marketing/data-storage-requirements
- Comments API (scope reference): https://learn.microsoft.com/linkedin/marketing/community-management/shares/comments-api
