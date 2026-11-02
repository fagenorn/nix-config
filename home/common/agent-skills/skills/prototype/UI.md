# UI Prototype

Several **radically different UI variants** on one route, switched from a floating bottom bar. The user flips between them in the browser, picks one or combines parts, and the rest is thrown away.

## Where the variants live

- **On an existing page (default).** Render the variants on the same route behind a `?variant=` search param, keeping its data fetching, params and auth; only the rendered subtree swaps. Something that would naturally live inside an existing page (a new section, card or step) is mounted there too. Variants judged against the real header, sidebar and data expose problems an empty page hides.
- **On a new throwaway route (last resort)**, only when nothing existing could host it. Follow the project's routing convention, put `prototype` in the path, and use the same `?variant=` switch.

## Process

1. **State the plan in one line** at the prototype's location, e.g. "Three variants of the settings page, switchable via `?variant=`, on the existing `/settings` route." Default to 3 variants, at most 5.
2. **Draft structurally different variants**: different layout, information hierarchy and primary affordance, not colours. Each uses the page's purpose and data, the project's component and styling system, and an exported name (`VariantA`, `VariantB`, ...). If two come out alike, redo one with an explicit constraint such as "no card grid".
3. **Wire one switcher** on the route, below any existing data fetching:

   ```tsx
   // pseudo-code — adapt to the project's framework
   const variant = searchParams.get('variant') ?? 'A';
   return (
     <>
       {variant === 'A' && <VariantA {...data} />}
       {variant === 'B' && <VariantB {...data} />}
       {variant === 'C' && <VariantC {...data} />}
       <PrototypeSwitcher variants={['A','B','C']} current={variant} />
     </>
   );
   ```

4. **Build the floating switcher** as one shared component wherever shared UI lives: a fixed bar at bottom centre with a left arrow, the current key plus the variant's name if it exports one (`B — Sidebar layout`), and a right arrow, both wrapping around.
   - Arrows update the search param through the framework router (`router.replace`, `navigate`) so a variant is shareable and survives reload.
   - `←`/`→` keys cycle too, except while an `<input>`, `<textarea>` or `[contenteditable]` has focus.
   - Styled visibly apart from the design under review.
   - Hidden in production builds (`process.env.NODE_ENV !== 'production'` or equivalent).
5. **Hand it over**: the URL and the `?variant=` keys. Expect feedback like "the header from B with the sidebar from C".
6. **Capture and clean up.** Record which variant won and why (commit message, ADR, issue, or a `NOTES.md` if the user hasn't answered). Then fold the winner into the existing page, or promote it to a real route, and delete the losing variants, the switcher and any throwaway route.

## Anti-patterns

- Variants that differ only in colour or copy.
- Sharing a layout between variants (a shared header is fine).
- Real mutations: point a variant that must mutate at a stub.
- Promoting prototype code as is: rewrite it properly when folding it in.
