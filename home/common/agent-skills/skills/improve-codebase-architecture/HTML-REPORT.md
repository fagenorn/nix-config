# HTML Report Format

One self-contained HTML file in the OS temp directory, with Tailwind and Mermaid from CDNs. Use Mermaid for graph-shaped diagrams and hand-built divs or inline SVG for the editorial ones; mix them.

## Contents

- Scaffold
- Candidate card, with its machine-checkable structure
- Safe rendering
- Diagrams
- Accessibility
- Style and tone

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Architecture review — {{repo name}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "strict", flowchart: { htmlLabels: false } });
    </script>
    <style>
      /* Minimal inline base layer: the report stays readable without the CDN. */
      body { font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.5; color: #0f172a;
             background: #fafaf9; margin: 0; overflow-wrap: anywhere; }
      main { max-width: 64rem; margin: 0 auto; padding: 3rem 1.5rem; }
      article, section { margin-block: 2rem; }
      img, svg { max-width: 100%; height: auto; }
      .before-after { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
      .seam { stroke-dasharray: 4 4; }
      .leak { stroke: #dc2626; }
      .deep { background: linear-gradient(135deg, #0f172a, #1e293b); color: #fff; }
      @media (max-width: 640px) { .before-after { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body class="bg-stone-50 text-slate-900 font-sans">
    <main class="max-w-5xl mx-auto px-6 py-12 space-y-12">
      <header>...</header>
      <section id="candidates" class="space-y-10">...</section>
      <section id="top-recommendation">...</section>
    </main>
  </body>
</html>
```

**Header**: repo name, date and a legend (solid box = module, dashed line = seam, red arrow labelled "leak" = leakage, thick dark box = deep module). No introduction; straight to the candidates.

## Candidate card

One `<article>` per candidate, with semantic headings in this order: **title** naming the deepening ("Collapse the Order intake pipeline"); a **badge row** with the strength (`Strong` emerald, `Worth exploring` amber, `Speculative` slate) and the dependency category; **files** in `font-mono text-sm`; the side-by-side **before / after diagram**; **problem** and **solution**, one sentence each; **wins**, bullets of at most six words; an amber **ADR callout** when one applies. No explanatory paragraphs: if a diagram needs one, redraw it.

### Machine-checkable structure

The report assertion reads these markers, so keep them exact:

- Each candidate is `<article data-architecture-candidate id="candidate-N">`, where `candidate-N` is an opaque generated ID, never repository text.
- Each candidate holds exactly one non-empty element per evidence marker, in scan order: `data-evidence="module-callers"`, `data-evidence="caller-interface-knowledge"`, `data-evidence="locality-leverage"`, `data-evidence="deletion-test"`, `data-evidence="dependency-adapters"`, `data-evidence="tests-interface-surface"`, `data-evidence="context-decision-conflict"`.
- Each candidate holds exactly one non-empty text equivalent per diagram state: `data-diagram-text="before"` and `data-diagram-text="after"`.
- A positive report has one to five candidate articles and exactly one `<section id="top-recommendation">` with exactly one anchor whose `href` names a candidate ID.
- A zero-candidate report has no candidate article and no top-recommendation section, and its candidates section holds exactly `<p id="no-candidates" data-candidate-count="0">No evidence-backed candidates.</p>` and nothing else.

## Safe rendering

HTML-escape every repository-derived value (repository, module, caller and file names, prose, evidence, decisions, diagram text) before inserting it into text or attributes: `&`, `<`, `>`, `"` and `'`. Never concatenate repository text into markup.

Mermaid shares the trust boundary: opaque generated node IDs (`node_1`), repository text only in escaped text labels, no raw HTML labels, and `securityLevel: "strict"` with `htmlLabels: false`. Edges join only generated IDs; repository text never becomes Mermaid directives, links, classes, styles or graph syntax.

## Diagrams

Pick the pattern that fits each candidate and vary them:

- **Mermaid graph** for call flow ("X calls Y calls Z"), in a Tailwind card, with `classDef` colouring leaks red and the deep module dark; a sequence diagram for "6 round-trips before, 1 after".
- **Hand-built boxes and arrows** (divs plus absolutely positioned SVG) when the "after" should read as one thick-bordered module with faded internals.
- **Cross-section**: stacked bands for the layers a call passes through, thin before and one thick band after.
- **Mass diagram**: an interface rectangle and an implementation rectangle per module, nearly equal before (shallow), short over tall after (deep).
- **Call-graph collapse**: nested call boxes before, one box with faded internal calls after.

Keep diagrams about 320px tall so before and after sit side by side.

## Accessibility

- One logical reading order: title, evidence, before, after, problem, solution, wins, any decision warning.
- Every diagram has an adjacent text equivalent naming the same modules, calls, seams, leaks and change; hide only the decorative drawing from assistive technology.
- Colour is never the only signal: pair badges, leak arrows and warnings with text or patterns. Normal text keeps at least 4.5:1 contrast.
- At phone width the before/after collapses to one column without duplicated content, and nothing is clipped; never lock card heights or suppress overflow.

## Style and tone

Editorial, not dashboard: generous whitespace, optional serif headings, one accent (emerald or indigo) plus red for leaks and amber for warnings, module labels in `text-xs uppercase tracking-wider`. The only scripts are the Tailwind CDN and the Mermaid import.

**Top recommendation**: one larger card with the candidate name, one sentence on why, and an anchor to its card; omitted only for a truthful zero-candidate result.

Use the `codebase-design` terms exactly (module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality), never component, service, unit, API, signature, boundary, layer or wrapper in their place. Wins name the gain in those terms ("locality: bugs concentrate in one module", "leverage: one interface, N call sites"), never "cleaner code". No hedging or throat-clearing.
