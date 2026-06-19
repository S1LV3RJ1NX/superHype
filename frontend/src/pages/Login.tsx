import { Wordmark } from "@/components/Wordmark";

export function Login() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-sm text-center">
        <Wordmark className="text-3xl" />
        <p className="mt-3 text-sm text-muted-ink">
          Human-in-the-loop employee advocacy for LinkedIn.
        </p>

        <div className="mt-8 rounded-lg border border-border bg-surface p-6">
          <button
            type="button"
            disabled
            className="flex w-full items-center justify-center gap-2 rounded-md bg-clay px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-clay-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            Continue with Google
          </button>
          <p className="mt-3 text-xs text-muted-ink">
            Sign-in is wired up in a later phase.
          </p>
        </div>
      </div>
    </div>
  );
}
