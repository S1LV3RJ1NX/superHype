import { useLayoutEffect, useRef, useState } from "react";
import {
  Bold,
  Code,
  Eye,
  Heading1,
  Heading2,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  Pencil,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minHeight?: number;
}

// Rendered-preview element styling. Kept here (not a Tailwind typography plugin)
// so the editor is self-contained and matches the app's tokens.
const MD_COMPONENTS = {
  h1: (props: object) => (
    <h1 className="mt-4 mb-2 text-xl font-semibold text-ink" {...props} />
  ),
  h2: (props: object) => (
    <h2 className="mt-4 mb-2 text-lg font-semibold text-ink" {...props} />
  ),
  h3: (props: object) => (
    <h3 className="mt-3 mb-1.5 text-base font-semibold text-ink" {...props} />
  ),
  p: (props: object) => <p className="my-2 text-sm text-ink" {...props} />,
  ul: (props: object) => (
    <ul className="my-2 list-disc pl-5 text-sm text-ink" {...props} />
  ),
  ol: (props: object) => (
    <ol className="my-2 list-decimal pl-5 text-sm text-ink" {...props} />
  ),
  li: (props: object) => <li className="my-0.5" {...props} />,
  a: (props: object) => (
    <a
      className="text-clay underline"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  strong: (props: object) => <strong className="font-semibold" {...props} />,
  code: (props: object) => (
    <code
      className="rounded bg-sand px-1 py-0.5 font-mono text-xs text-ink"
      {...props}
    />
  ),
  blockquote: (props: object) => (
    <blockquote
      className="my-2 border-l-2 border-border pl-3 text-sm text-muted-ink"
      {...props}
    />
  ),
};

export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  minHeight = 360,
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<"write" | "preview">("write");
  const ref = useRef<HTMLTextAreaElement>(null);
  // A selection to restore after a toolbar edit re-renders the controlled value.
  const pendingSelection = useRef<[number, number] | null>(null);

  useLayoutEffect(() => {
    if (pendingSelection.current && ref.current) {
      const [start, end] = pendingSelection.current;
      ref.current.focus();
      ref.current.setSelectionRange(start, end);
      pendingSelection.current = null;
    }
  });

  const apply = (next: string, selStart: number, selEnd: number) => {
    pendingSelection.current = [selStart, selEnd];
    onChange(next);
  };

  // Wrap the current selection with a prefix/suffix (bold, italic, code, link).
  const wrap = (before: string, after: string, placeholderText = "") => {
    const el = ref.current;
    if (!el) return;
    const { selectionStart: s, selectionEnd: e } = el;
    const selected = value.slice(s, e) || placeholderText;
    const next = value.slice(0, s) + before + selected + after + value.slice(e);
    apply(next, s + before.length, s + before.length + selected.length);
  };

  // Prefix every line touched by the selection (headings, quotes, lists).
  const linePrefix = (prefix: string | ((i: number) => string)) => {
    const el = ref.current;
    if (!el) return;
    const { selectionStart: s, selectionEnd: e } = el;
    const lineStart = value.lastIndexOf("\n", s - 1) + 1;
    const block = value.slice(lineStart, e);
    let i = 0;
    const updated = block
      .split("\n")
      .map((line) => (typeof prefix === "string" ? prefix : prefix(i++)) + line)
      .join("\n");
    const next = value.slice(0, lineStart) + updated + value.slice(e);
    apply(next, lineStart, lineStart + updated.length);
  };

  // Tab indents (2 spaces); Shift+Tab outdents. Kept inside the editor instead
  // of moving focus, which is what the browser does by default.
  const onKeyDown = (ev: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (ev.key !== "Tab") return;
    ev.preventDefault();
    const el = ev.currentTarget;
    const { selectionStart: s, selectionEnd: e } = el;
    const lineStart = value.lastIndexOf("\n", s - 1) + 1;
    const multiline = value.slice(s, e).includes("\n");

    if (ev.shiftKey) {
      const block = value.slice(lineStart, e);
      const lines = block.split("\n");
      let removedFirst = 0;
      let removedTotal = 0;
      const outdented = lines
        .map((line, idx) => {
          const cut = line.startsWith("  ") ? 2 : line.startsWith(" ") ? 1 : 0;
          if (idx === 0) removedFirst = cut;
          removedTotal += cut;
          return line.slice(cut);
        })
        .join("\n");
      const next = value.slice(0, lineStart) + outdented + value.slice(e);
      apply(next, Math.max(lineStart, s - removedFirst), e - removedTotal);
      return;
    }

    if (multiline) {
      const block = value.slice(lineStart, e);
      const indented = block
        .split("\n")
        .map((line) => "  " + line)
        .join("\n");
      const next = value.slice(0, lineStart) + indented + value.slice(e);
      const added = 2 * block.split("\n").length;
      apply(next, s + 2, e + added);
      return;
    }

    const next = value.slice(0, s) + "  " + value.slice(e);
    apply(next, s + 2, s + 2);
  };

  const tools = [
    { icon: Heading1, title: "Heading 1", run: () => linePrefix("# ") },
    { icon: Heading2, title: "Heading 2", run: () => linePrefix("## ") },
    { icon: Bold, title: "Bold", run: () => wrap("**", "**", "bold text") },
    { icon: Italic, title: "Italic", run: () => wrap("_", "_", "italic text") },
    { icon: List, title: "Bulleted list", run: () => linePrefix("- ") },
    {
      icon: ListOrdered,
      title: "Numbered list",
      run: () => linePrefix((i) => `${i + 1}. `),
    },
    { icon: Code, title: "Inline code", run: () => wrap("`", "`", "code") },
    {
      icon: LinkIcon,
      title: "Link",
      run: () => wrap("[", "](https://)", "link text"),
    },
  ];

  return (
    <div className="rounded-md border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
        <div className={cn("flex flex-wrap gap-0.5", mode === "preview" && "opacity-40")}>
          {tools.map(({ icon: Icon, title, run }) => (
            <button
              key={title}
              type="button"
              title={title}
              disabled={mode === "preview"}
              onClick={run}
              className="rounded p-1.5 text-muted-ink hover:bg-sand disabled:cursor-not-allowed"
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setMode(mode === "write" ? "preview" : "write")}
          className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs text-muted-ink hover:bg-sand"
        >
          {mode === "write" ? (
            <>
              <Eye className="h-3.5 w-3.5" />
              Preview
            </>
          ) : (
            <>
              <Pencil className="h-3.5 w-3.5" />
              Write
            </>
          )}
        </button>
      </div>

      {mode === "write" ? (
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          spellCheck={false}
          style={{ minHeight }}
          className="w-full resize-y rounded-b-md bg-surface px-3 py-2 font-mono text-sm text-ink focus:outline-none"
        />
      ) : (
        <div
          style={{ minHeight }}
          className="overflow-auto px-3 py-2"
        >
          {value.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
              {value}
            </ReactMarkdown>
          ) : (
            <p className="text-sm text-muted-ink">Nothing to preview yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
