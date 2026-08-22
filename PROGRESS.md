# Progress

## 2026-08-22: Dealer knowledge hub pilot

- Added the `/app/knowledge` entry for human evidence search and cited AI answers.
- Added same-origin PDCA proxy APIs with five-minute scoped service tokens.
- Added dealer UUID mapping, team mapping, role enforcement, and admin-only original export.
- Corrected VMG ownership to 尤文静 and deduplicated its four stores into one knowledge dealer.
- Added production Compose key-file mounting and an operations acceptance runbook.

Verification:

- Backend: `162 tests` passed; Python compilation passed.
- Frontend: `vue-tsc --noEmit` and Vite production build passed.
- Docker Compose production configuration passed with disposable validation values.
- Real local PostgreSQL/data-hub path: search, watermarked preview, sales export `403`, admin export `200`.
- Playwright desktop and `390x844`: 8 results, 8/8 images loaded, first result `image12.png`, zero console errors, no horizontal overflow.

Production cutover remains pending until RDS, OSS, Redis, DNS/TLS, shared key files, OpenRouter policy/key, and media-model preload are configured and accepted in the target environment.
