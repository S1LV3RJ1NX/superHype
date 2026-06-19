import { cn } from "@/lib/utils";

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-serif text-ink", className)}>
      super<span className="text-clay">-</span>hype
    </span>
  );
}
