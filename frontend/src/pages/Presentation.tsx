// The launch deck is a single self-contained HTML file in public/, so we serve
// it verbatim in a full-viewport iframe. This keeps the deck's own styles and
// keyboard navigation intact while giving it a clean /presentation URL that
// works the same in dev (Vite) and prod (nginx SPA fallback). Public on purpose
// so it can be shared without a login.
export function Presentation() {
  return (
    <iframe
      src="/presentation.html"
      title="superHype launch presentation"
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        border: "none",
      }}
    />
  );
}
