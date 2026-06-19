import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";

export function Wordmark({
  className,
  showMark = true,
}: {
  className?: string;
  showMark?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-serif font-semibold tracking-tight text-ink",
        className,
      )}
    >
      {showMark && <Logo className="h-[1.15em] w-[1.15em] shrink-0" />}
      <span>
        super<span className="text-clay">-</span>hype
      </span>
    </span>
  );
}
