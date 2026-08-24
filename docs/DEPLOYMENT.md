# Deployment

1. Start from current `main` and create one `codex/<task>` worktree.
2. Run backend tests, frontend typecheck/build, Compose validation, and browser acceptance.
3. Review and merge. Deploy only the reviewed `main` commit.
4. Mount the same read-only JWT key into PDCA and data-hub. Keep all secrets outside Git and images.
5. Back up PostgreSQL before migration or bulk import; record commit, migration result, health result, and rollback point.
6. Roll back application code to the previous reviewed commit. Keep schema changes backward compatible.

Production details remain in `pdca-workbench/docs/部署手册.md` and `pdca-workbench/docs/运维手册-P5.md`.
