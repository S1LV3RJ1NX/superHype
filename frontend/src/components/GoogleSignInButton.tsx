import { cn } from "@/lib/utils";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

function GoogleGlyph({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72A5.41 5.41 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"
      />
    </svg>
  );
}

export function GoogleSignInButton({
  variant = "primary",
  className,
}: {
  variant?: "primary" | "outline";
  className?: string;
}) {
  // The real OAuth handoff lands in Phase 1; this points at the backend login route.
  const handleSignIn = () => {
    window.location.href = `${API_BASE}/v1/google/login`;
  };

  return (
    <button
      type="button"
      onClick={handleSignIn}
      className={cn(
        "inline-flex items-center justify-center gap-2.5 rounded-md px-5 py-2.5 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
        variant === "primary"
          ? "bg-clay text-primary-foreground hover:bg-clay-press"
          : "border border-border bg-surface text-ink hover:bg-sand",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-4 w-4 items-center justify-center rounded-sm",
          variant === "primary" ? "bg-white p-0.5" : "",
        )}
      >
        <GoogleGlyph className="h-3.5 w-3.5" />
      </span>
      Continue with Google
    </button>
  );
}
