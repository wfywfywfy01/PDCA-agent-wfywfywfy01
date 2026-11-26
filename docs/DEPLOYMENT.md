# Deployment

1. Start from current `main` and create one `codex/<task>` worktree.
2. Run backend tests, frontend typecheck/build, Compose validation, and browser acceptance.
3. Review and merge. Deploy only the reviewed `main` commit.
4. Mount the same read-only JWT key into PDCA and data-hub. Keep all secrets outside Git and images.
5. Back up PostgreSQL before migration or bulk import; record commit, migration result, health result, and rollback point.
6. Roll back application code to the previous reviewed commit. Keep schema changes backward compatible.

Production details remain in `pdca-workbench/docs/部署手册.md` and `pdca-workbench/docs/运维手册-P5.md`.

## WorkBench VPS session for PDCA Five Kit

On the `pdca-workbench-teams.vertu.cn` Caddy site, keep this exact route before
`handle_path /gtm/*`. The WorkBench login cookie is scoped to `/gtm/`; PDCA
validates the session with GTM before granting Five Kit read access.

```caddyfile
handle /gtm/api/workbench-five-kit {
    rewrite * /api/auth/workbench-five-kit
    reverse_proxy 127.0.0.1:8771
}
handle /gtm/api/workbench-data {
    rewrite * /api/auth/workbench-data
    reverse_proxy 127.0.0.1:8768
}
```

Preserve the other production routes, back up the Caddyfile, and validate it
before reload. An unauthenticated POST to this route with the same-origin
`Origin` and `X-WorkBench-Source: pdca-five-kit` headers should return HTTP 401.

The `workbench-data` route validates the same session and runs read-only search,
sales queries and meeting todo queries. The main container owns upstream
credentials. Vemory matches the verified VPS ID in `PDCA_VEMORY_TODO_USERS`.
AINativeSales can use `PDCA_WORKBENCH_AISALES_VPS_TOKEN`. Its existing personal
credential is usable only when the MCP principal matches the current VPS user.
