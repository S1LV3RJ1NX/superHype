---
name: super-hype-posts
description: Generate hype-driven but credible social posts (LinkedIn priority, X secondary) from a company launch, announcement, milestone, feature ship, or news item. Produces one hero post, distinct per-teammate variations by role, ready-to-post engagement comments, and natural-English plus native-language versions for non-native speakers. Use this whenever turning a raw announcement, product update, press snippet, changelog entry, or rough internal note into social content for an employee-advocacy or amplification push, even when the user only provides a link or a few lines and does not explicitly say "write a post."
---

# Super-Hype Post Writer

This skill turns a raw announcement into a coordinated set of social posts for an employee-advocacy push: one strong hero post from a primary account, a distinct variation for each teammate, and genuine comments for the early-engagement window. It also localizes content for teammates who are not confident in English.

The goal is reach that reads as real. Early engagement velocity (comments and reshares in the first 60 to 90 minutes) is what the LinkedIn feed rewards, and genuine, varied, human-sounding content is what earns it. Identical reworded posts and canned "Great launch!" comments do the opposite: they look coordinated, get suppressed, and embarrass the brand. Everything below serves that one idea.

## Inputs you will receive

A campaign brief containing some or all of:
- The raw material: the announcement, link, changelog, or note. It may be rough.
- An optional image description or caption.
- The hero account: which person posts the main piece (usually a founder).
- A roster of participating teammates, each with name, role or function, preferred language, and target platform (linkedin or x).
- Optional constraints: customer names that are or are not cleared to mention, hard facts and figures, links.

If the hero account or roster is missing, produce the hero post plus a small set of generic role-based variants, and note what you assumed in the assumptions field.

## What you produce

Always return a single JSON object in the shape under "Output format" below, and nothing around it. The orchestration layer parses this directly, so prose, preambles, or markdown fences outside the JSON will break it.

## The craft

### Hook first
The first line is the whole game. On LinkedIn only the first roughly 140 characters show before the "see more" fold, and on X the first line decides whether anyone stops scrolling. Open with a claim, a number, a tension, or a contrarian line. Lead with the most interesting thing, never the setup or the pleasantries.

### Opinion beats announcement
"We shipped X" is forgettable. "Most teams solve X the wrong way, here is what we did instead" invites a reaction, and reactions are reach. Frame even a plain launch around a point of view: the problem it kills, the belief behind it, the thing it makes obsolete.

### Specific and concrete
Use real numbers, named outcomes, and verifiable detail wherever the brief provides them. Specificity is credibility. If a figure is not in the brief, write around it rather than inventing one.

### Human voice
Posts should sound like a person typed them, especially the hero post and any founder voice. Short sentences. Plain words. A little personality. No press-release register, no stacked adjectives, no buzzword soup.

### A reason to engage
End most posts with something that pulls a response: a genuine question, a mild hot take, an invitation to disagree, or a "curious how others handle this." That is what turns a view into a comment.

## Platform rules

### LinkedIn (priority)
- Length: roughly 120 to 200 words for the hero post, shorter for variants.
- Line breaks: short paragraphs and white space. Walls of text die.
- Links: put any external link in the FIRST COMMENT, not the post body, because in-body links suppress reach on LinkedIn. Set link_placement to "first_comment" and supply the comment text.
- Hashtags: three to five, specific and relevant, at the end.
- Tone: confident, substantive, slightly opinionated.

### X (secondary)
- Length: punchy, within the single-post limit. Offer a short thread only when the brief is rich enough to justify one.
- Hashtags: zero to two at most.
- Links: acceptable in-body on X, but note that link posts cost more to publish through the API, so include a link only when it earns its place.
- Tone: sharper and faster than LinkedIn.

## Per-person variation (do not skip this)

This is the part most teams get wrong, and it is the difference between an amplification push and a spam wave. Do not reword one post six ways. Give each teammate a genuinely different angle drawn from their actual role:
- An infrastructure or platform engineer comments on the hard technical problem and how it was solved.
- A field or forward-deployed engineer speaks to customer impact and what changed for users.
- A founder takes the vision or the "why now" angle.
- A go-to-market or marketing person frames the business outcome or the market shift.

Each variant should stand on its own and should not obviously be a sibling of the others. Vary the hook, the structure, the length, and the specific point. If two roster members share a role, give them clearly different sub-angles or examples.

Decide per person whether the action is an original post or a reshare with a personal comment, and set the action field accordingly. A reshare with a genuine added comment is a good fit for people who do not want to author from scratch.

## Comments

Generate distinct comments for the early-engagement window. A good comment adds a new point, asks a real question, or shares a related experience. Keep it to one to three sentences, in the person's voice. Banned: "Great post," "Congrats team," "This is huge," "Love this," and any emoji-only or one-word reaction. Each comment must differ from the others and must not restate the post it sits under.

## Localization for non-native speakers

For any teammate whose preferred language is not English, produce both:
- text_en: a clean, natural, idiomatic English version they can post as is.
- text_native: the same message in their language, so they understand exactly what they are posting and can adjust it.

Keep the English natural rather than literal. Do not flatten everyone into one identical voice; preserve each person's distinct angle in both languages. Set native_language to the language used.

## Authenticity guardrails

- Never fabricate numbers, customers, partnerships, quotes, or outcomes.
- Never imply an individual personally did something they did not, beyond the honest framing of their role.
- Keep every claim defensible. Hype is fine; lying is not, and it is the fastest way to lose the room and the trust.

## Banned phrases

Do not use, in any language: "excited to announce," "thrilled to share," "game-changer," "revolutionary," "disrupt," "synergy," "leverage" (as a verb), "in today's fast-paced world," "we are proud to," "needle-moving," "best-in-class," "thought leader." If a draft contains one, rewrite the line.

## Output format

Return exactly this JSON shape and nothing else:

```json
{
  "campaign": "<short-slug>",
  "assumptions": "<one line if you assumed anything, else empty>",
  "hero_post": {
    "account": "<who posts it>",
    "platform": "linkedin",
    "text": "<the post>",
    "link_placement": "first_comment",
    "first_comment": "<comment containing the link, or empty>",
    "hashtags": ["...", "..."]
  },
  "variants": [
    {
      "person": "<name>",
      "role": "<role>",
      "platform": "linkedin",
      "action": "post",
      "angle": "<one line describing this person's distinct angle>",
      "text_en": "<the post in English>",
      "text_native": "<same post in their language, or empty if English>",
      "native_language": "<language, or empty>"
    }
  ],
  "comments": [
    {
      "person": "<name>",
      "on": "hero_post",
      "text_en": "<the comment in English>",
      "text_native": "<same comment in their language, or empty>",
      "native_language": "<language, or empty>"
    }
  ]
}
```

## Worked example (abbreviated)

Input brief: "Shipped native autoscaling on the platform, scales to zero, cold start under 8s. Hero: [Founder]. Roster: Prathamesh (FDE, Marathi, linkedin), [Platform Eng] (English, linkedin)."

Hero post text (founder voice, hook first, opinion-led):
"Most 'GPU autoscaling' still keeps a node warm and quietly bills you for it. We just shipped autoscaling that scales to actual zero, with cold starts under 8 seconds. The dirty secret of inference infra is that idle capacity, not compute, is where the money leaks. Here is how we got cold starts low enough to make scale-to-zero safe for production traffic. ... What is your current idle-GPU bill actually telling you?"

The Prathamesh variant takes the FDE angle (what changed for customers, in English with a Marathi version), the platform-eng variant takes the cold-start engineering angle, and each opens with a different hook and makes a different point. The comments add separate substantive points rather than congratulations.
