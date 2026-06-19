import { AppShell } from "@/components/AppShell";

export function Placeholder({ title, phase }: { title: string; phase: number }) {
  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        <h1 className="font-serif text-2xl text-ink">{title}</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Coming in Phase {phase}.
        </p>
        <div className="mt-6 rounded-lg border border-border bg-surface p-10 text-center">
          <p className="text-sm text-muted-ink">
            This page will be built in a later phase.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
