// The super-hype mark: a clay badge with rising broadcast waves, echoing one
// announcement amplified into many. Uses theme CSS variables so it stays on
// palette. The standalone favicon (public/favicon.svg) mirrors this with literal
// hex values, since browser chrome cannot read page CSS variables.
export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="super-hype logo"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width="32" height="32" rx="9" fill="hsl(var(--clay))" />
      <path
        d="M8.5 21a7.5 7.5 0 0 1 15 0"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M12 21a4 4 0 0 1 8 0"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <circle cx="16" cy="21" r="2" fill="white" />
    </svg>
  );
}
