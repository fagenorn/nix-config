# Wide refactors — the exception to vertical slicing

A wide refactor is one mechanical change (rename a column, retype a shared
symbol) that breaks call sites across the whole codebase at once, so no
vertical slice lands green. Sequence it as **expand–contract**:

1. **Expand**: add the new form beside the old so nothing breaks.
2. **Migrate**: convert call sites in batches sized by blast radius (per
   package or directory), each its own slice blocked by the expand, green
   batch to batch because the old form still exists.
3. **Contract**: delete the old form in a slice blocked by every migrate batch.

When even the batches cannot stay green alone, they share an integration
branch and all block a final integrate-and-verify slice; green is promised
only there.
