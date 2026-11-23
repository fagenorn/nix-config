# Retire the deploy watch

This is the migration `bindings-deploy.retire`, from project schema 1 to 2 (issue 579).

The migration `bindings-deploy.retire`, per project root R:

1. `bindings.deploy.adapter` is `none` and `capabilities.deploy.support` is `unsupported`.
2. `adopt-project migrate --migration bindings-deploy.retire --repo-root R`.
3. Commit `.agents/project.json` and the regenerated projections.
4. `removed_uses` no longer lists `bindings-deploy`.
