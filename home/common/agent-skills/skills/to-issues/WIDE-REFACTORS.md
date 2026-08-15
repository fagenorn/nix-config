# Wide refactors — the exception to vertical slicing

Read this when a slice candidate is one mechanical change with codebase-wide
blast radius.

A wide refactor is one mechanical change — rename a column, retype a shared
symbol — whose blast radius fans across the whole codebase, so a single edit
breaks thousands of call sites at once and no vertical slice can land green.
Don't force it into a tracer bullet; sequence it as **expand–contract**:

1. **Expand** — add the new form beside the old so nothing breaks.
2. **Migrate** — convert the call sites in batches sized by blast radius (per
   package, per directory), each batch its own slice blocked by the expand,
   keeping CI green batch to batch because the old form still exists.
3. **Contract** — delete the old form once no caller remains, in a slice blocked
   by every migrate batch.

When even the batches can't stay green alone, keep the sequence but let them
share an integration branch that all block a final integrate-and-verify slice —
green is promised only there.
