import { AppShell } from "@/components/AppShell";

export function Dashboard() {
  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        <h1 className="font-serif text-2xl text-ink">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-ink">
          Campaigns and your pending approvals will live here.
        </p>

        <div className="mt-6 rounded-lg border border-border bg-surface p-10 text-center">
          <p className="text-sm text-muted-ink">
            No campaigns yet. The composer arrives in a later phase.
          </p>
        </div>

        <div className="mt-6 flex items-center gap-4 text-sm">
          <span className="inline-flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-ok" /> Published
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-pending" /> Pending
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-fail" /> Failed
          </span>
        </div>
      </div>
    </AppShell>
  );
}
