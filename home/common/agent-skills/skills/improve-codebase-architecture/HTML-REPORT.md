# HTML Report Format

The architectural review is rendered as a single self-contained HTML file in the OS temp directory. Tailwind and Mermaid both come from CDNs. Mermaid handles graph-shaped diagrams reliably; hand-built divs and inline SVG handle the more editorial visuals (mass diagrams, cross-sections). Mix the two — don't lean on Mermaid for everything, it'll start to look generic.

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
      /* This minimal inline base layer keeps the report readable without the CDN. */
      body {
        font-family: ui-sans-serif, system-ui, sans-serif;
        line-height: 1.5;
        color: #0f172a;
        background: #fafaf9;
        margin: 0;
        overflow-wrap: anywhere;
      }
      main { max-width: 64rem; margin: 0 auto; padding: 3rem 1.5rem; }
      article, section { margin-block: 2rem; }
      img, svg { max-width: 100%; height: auto; }
      .before-after {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
      }
      /* small custom layer for things Tailwind doesn't cover cleanly:
         dashed seam lines, hand-drawn-feeling arrow heads, etc. */
      .seam { stroke-dasharray: 4 4; }
      .leak { stroke: #dc2626; }
      .deep { background: linear-gradient(135deg, #0f172a, #1e293b); color: #fff; }
      @media (max-width: 640px) {
        .before-after { grid-template-columns: 1fr; }
      }
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

## Header

Repo name, date, and a compact legend: solid box = module, dashed line = seam, red arrow and a "leak" label = leakage, thick dark box = deep module. No introduction paragraph — straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse, plain, and uses the glossary terms (from the `codebase-design` skill) without ceremony.

Each candidate is one `<article>` with semantic headings in source and reading order:

- **Title** — short, names the deepening (e.g. "Collapse the Order intake pipeline").
- **Badge row** — recommendation strength (`Strong` = emerald, `Worth exploring` = amber, `Speculative` = slate), plus a tag for the dependency category (`in-process`, `local-substitutable`, `ports & adapters`, `mock`).
- **Files** — monospaced list, `font-mono text-sm`.
- **Before / After diagram** — the centrepiece. Two columns, side by side. See patterns below.
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each. e.g. "Tests hit one interface", "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (if applicable) — one line in an amber-tinted box.

No paragraphs of explanation. If the diagram needs a paragraph to be understood, redraw the diagram.

### Machine-checkable report structure

The deployed report assertion reads semantic markers rather than searching for words. Keep this structure exact:

- Each candidate is `<article data-architecture-candidate id="candidate-N">`, where `candidate-N` is an opaque generated ID rather than repository text.
- Each candidate contains exactly one non-empty element for each evidence marker, in scan order: `data-evidence="module-callers"`, `data-evidence="caller-interface-knowledge"`, `data-evidence="locality-leverage"`, `data-evidence="deletion-test"`, `data-evidence="dependency-adapters"`, `data-evidence="tests-interface-surface"`, and `data-evidence="context-decision-conflict"`.
- Each candidate contains exactly one non-empty adjacent text equivalent for each diagram state: `data-diagram-text="before"` and `data-diagram-text="after"`.
- A positive report contains one to five candidate articles and exactly one `<section id="top-recommendation">` with exactly one anchor whose `href` names one candidate ID.
- A zero-candidate report contains zero candidate articles, omits the top-recommendation section, and renders exactly one `<p id="no-candidates" data-candidate-count="0">No evidence-backed candidates.</p>` as the only element or non-whitespace text inside the candidates section.

## Safe rendering boundary

HTML-escape every repository-derived value before inserting it into the scaffold, whether it appears in text or an attribute. This includes repository, module, caller, and file names; prose; evidence; decisions; and diagram text equivalents. Escape `&`, `<`, `>`, `"`, and `'`; for example, `<img title='repo' onerror="alert(1)">&` becomes `&lt;img title=&#x27;repo&#x27; onerror=&quot;alert(1)&quot;&gt;&amp;`. Never concatenate repository text into markup.

Mermaid has the same trust boundary. Use opaque generated node IDs such as `node_1`, never repository-derived IDs. Put repository text only in escaped text labels, use no raw HTML labels, and keep `securityLevel: "strict"` with `htmlLabels: false`. Edges may connect only the generated IDs; repository text never becomes Mermaid directives, link targets, classes, styles, or raw graph syntax.

## Diagram patterns

Pick the pattern that fits the candidate. Mix them. Don't make every diagram look the same — variety is part of the point.

### Mermaid graph (the workhorse for dependencies / call flow)

Use a Mermaid `flowchart` or `graph` when the point is "X calls Y calls Z, and look at the mess." Wrap it in a Tailwind-styled card so it doesn't feel parachuted in. Style with classDef to colour leakage edges red and the deep module dark. Sequence diagrams work well for "before: 6 round-trips; after: 1."

```html
<div class="rounded-lg border border-slate-200 bg-white p-4">
  <pre class="mermaid" aria-hidden="true">
    flowchart LR
      A[OrderHandler] --> B[OrderValidator]
      B --> C[OrderRepo]
      C -.leak.-> D[PricingClient]
      classDef leak stroke:#dc2626,stroke-width:2px;
      class C,D leak
  </pre>
  <p class="diagram-text">Text equivalent: OrderHandler calls OrderValidator, then OrderRepo; OrderRepo leaks pricing knowledge to PricingClient.</p>
</div>
```

### Hand-built boxes-and-arrows (when Mermaid's layout fights you)

Modules as `<div>`s with borders and labels. Arrows as inline SVG `<line>` or `<path>` elements positioned absolutely over a relative container. Reach for this when you want the "after" diagram to feel like one thick-bordered deep module with greyed-out internals — Mermaid won't render that with the right weight.

### Cross-section (good for layered shallowness)

Stack horizontal bands (`h-12 border-l-4`) to show layers a call passes through. Before: 6 thin layers each doing nothing. After: 1 thick band labelled with the consolidated responsibility.

### Mass diagram (good for "interface as wide as implementation")

Two rectangles per module — one for interface surface area, one for implementation. Before: interface rectangle is nearly as tall as the implementation rectangle (shallow). After: interface rectangle is short, implementation rectangle is tall (deep).

### Call-graph collapse

Before: a tree of function calls rendered as nested boxes. After: the same tree collapsed into one box, with the now-internal calls shown faded inside it.

## Accessibility and resilient rendering

- Use semantic headings and preserve one logical reading order: title, evidence, before, after, problem, solution, wins, and any decision warning.
- Give every diagram an adjacent text equivalent that communicates the same modules, calls, seams, leaks, and change. Hide only the decorative drawing from assistive technology; never the equivalent.
- Meaning survives monochrome: colour is never the sole signal. Pair badge colours, leak arrows, and warning tints with visible text labels or patterns.
- Keep normal text at least 4.5:1 contrast against its background. The minimal inline base styles preserve readable prose when Tailwind or Mermaid cannot load.
- At phone width the single before/after source collapses to one column without duplicating content. Diagrams, labels, paths, and code wrap or scale so text is not clipped.
- Do not lock card heights or suppress overflow: user spacing overrides must expand the document without obscuring or clipping content.

## Style guidance

- Lean editorial, not corporate-dashboard. Generous whitespace. Serif optional for headings (`font-serif` works well with stone/slate).
- Colour sparingly: one accent (emerald or indigo) plus red for leakage and amber for warnings.
- Keep diagrams ~320px tall so before/after sits comfortably side by side without scrolling at desktop width.
- Use `text-xs uppercase tracking-wider` for module labels inside diagrams — they should read as schematic, not as UI.
- The only scripts are the Tailwind CDN and the Mermaid ESM import. The report is otherwise static — no app code, no interactivity beyond Mermaid's own rendering.

## Top recommendation section

One larger card. Candidate name, one sentence on why, anchor link to its card. That's it. Omit this section only for a truthful zero-candidate result.

## Tone

Plain English, concise — but the architectural nouns and verbs come straight from the `codebase-design` skill. Concision is not an excuse to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API, signature (for interface) · boundary (for seam) · layer, wrapper (for module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: *"locality: bugs concentrate in one module"*, *"leverage: one interface, N call sites"*, *"interface shrinks; implementation absorbs the wrappers"*. Don't write *"easier to maintain"* or *"cleaner code"* — those terms aren't in the glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. If a term isn't in the `codebase-design` glossary, reach for one that is before inventing a new one.
