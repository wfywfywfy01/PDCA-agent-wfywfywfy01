# Architecture

PDCA is the operating workbench and identity boundary. It owns users, roles, sales ownership, dealer assignments, dashboards, and workflow entry points.

`vertu-data-hub` is a separate service and repository. It owns dealer master records, source files, immutable asset versions, ETL, embeddings, retrieval, citations, previews, and content-access audits.

PDCA never reads the data-hub database directly. Its server creates a scoped, five-minute JWT and calls the private data-hub API. Browsers call only same-origin PDCA endpoints and never receive the shared signing key or OSS credentials.

See `pdca-workbench/docs/经销商资料库接入与验收.md` for the detailed scope model and acceptance contract.
