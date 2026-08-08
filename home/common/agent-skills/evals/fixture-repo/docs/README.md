# tinytask docs

| Entry | What lives there |
|---|---|
| [CONTEXT-MAP.md](./CONTEXT-MAP.md) | The map: the areas, the paths each governs, and which area owns each term |
| [areas/](./areas/) | One directory per area — a budgeted glossary plus that area's decision records |
| [standards/](./standards/) | The coding bar for this repo |

**Where new knowledge goes.** A term or an invariant belongs in the owning area's
`CONTEXT.md`. A hard-to-reverse decision belongs in that area's `adr/`, or in
`areas/system/adr/` when it spans areas. A rule about how code gets written belongs in
`standards/`. Specs, plans and handoffs are not documentation — they live in `.claude/`.
