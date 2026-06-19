import {
  CheckCircle2,
  Clock,
  Lock,
  MessageSquare,
  PenLine,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { Wordmark } from "@/components/Wordmark";

const STEPS = [
  {
    icon: PenLine,
    title: "Draft",
    body: "Drop in a raw announcement and pick a writing style. The model writes a hero post plus a distinct variant and comment for every teammate.",
  },
  {
    icon: CheckCircle2,
    title: "Approve",
    body: "Each person gets a one-tap approve, edit, or skip in Slack or the web app. Real people approve real posts. Nothing publishes without them.",
  },
  {
    icon: Clock,
    title: "Publish on a stagger",
    body: "Approved posts go out through LinkedIn's official API on a randomized schedule, clustered in the golden hour, never all at once.",
  },
];

const FEATURES = [
  {
    icon: Sparkles,
    title: "Genuine variety",
    body: "Every teammate gets a different angle drawn from their role, not one post reworded six ways.",
  },
  {
    icon: ShieldCheck,
    title: "Official API only",
    body: "No scraping, no credential capture. Every action runs on each member's own LinkedIn consent.",
  },
  {
    icon: MessageSquare,
    title: "One tap in Slack",
    body: "The wider team approves from a Slack DM. The web app is the same flow for anyone who prefers it.",
  },
];

export function Landing() {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Wordmark className="text-xl" />
        <GoogleSignInButton variant="outline" className="px-4 py-2" />
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-16 pt-4 md:grid-cols-2 md:pb-20 md:pt-10">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-sand px-3 py-1 text-xs font-medium text-muted-ink">
              <Sparkles className="h-3.5 w-3.5 text-clay" />
              Employee advocacy, minus the spam
            </span>
            <h1 className="mt-5 font-serif text-4xl leading-tight tracking-tight text-ink md:text-5xl">
              Turn one announcement into a wave of posts that read as real.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-muted-ink">
              super-hype drafts a hero post and a distinct variant for everyone
              on the team, routes each one for a one-tap human approval, and
              publishes on a stagger through LinkedIn's official API. Genuine
              engagement, concentrated in the first ninety minutes.
            </p>
            <div className="mt-8">
              <GoogleSignInButton />
              <p className="mt-3 flex items-center gap-1.5 text-sm text-muted-ink">
                <Lock className="h-3.5 w-3.5 text-clay" />
                Sign in with your company Google account.
              </p>
            </div>
          </div>

          {/* Signature: one announcement fanning out into many authentic posts. */}
          <div className="relative">
            <img
              src="/banner-compressed.jpg"
              alt="One announcement fanning out into a staggered wave of authentic LinkedIn posts"
              className="w-full rounded-xl border border-border shadow-sm"
            />
            {/* <div className="absolute -bottom-4 -right-3 hidden rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-ok shadow-sm sm:flex sm:items-center sm:gap-2">
              <span className="h-2 w-2 rounded-full bg-ok" />
              Published 12:04
            </div> */}
          </div>
        </section>

        {/* How it works */}
        <section className="border-y border-border bg-sand/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 className="font-serif text-2xl text-ink">
              Three steps, one launch.
            </h2>
            <div className="mt-8 grid gap-6 md:grid-cols-3">
              {STEPS.map(({ icon: Icon, title, body }) => (
                <div
                  key={title}
                  className="rounded-lg border border-border bg-surface p-6"
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-md bg-clay/10">
                    <Icon className="h-5 w-5 text-clay" />
                  </div>
                  <h3 className="mt-4 text-base font-medium text-ink">
                    {title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-ink">
                    {body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="font-serif text-2xl text-ink">
            Reach that reads as real.
          </h2>
          <div className="mt-8 grid gap-6 md:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex gap-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-sand">
                  <Icon className="h-5 w-5 text-clay" />
                </div>
                <div>
                  <h3 className="text-base font-medium text-ink">{title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-ink">
                    {body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-6 py-6 text-xs text-muted-ink sm:flex-row">
          <Wordmark className="text-sm" />
          <span>
            Created by{" "}
            <span className="font-medium text-ink">Prathamesh Saraf</span> ·
            Internal tool, company sign-in only.
          </span>
        </div>
      </footer>
    </div>
  );
}
