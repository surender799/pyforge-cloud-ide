# Security and deployment boundary

PyForge is a local learning/development system. It binds to loopback and assumes trusted local users. It does not provide internet-facing authentication, tenant isolation, or production operational controls.

Editing uses whole-file optimistic concurrency, not CRDT merging; conflicting edits require manual reconciliation. One shared workspace per process. This is a local, single-user development server with multiple browser sessions, not a hosted multi-tenant IDE. The terminal is a line-oriented shell, not a PTY. Containers require a running Docker engine and the Python image; there is no unsafe host-execution fallback.

Do not place credentials in example programs, repository fixtures, or runtime files committed to Git. Report security issues privately through the repository owner's GitHub contact options rather than publishing working attacks against a deployed system.

Before any public deployment, design authentication, authorization, TLS, request quotas, resource limits, backups, and abuse controls appropriate to the application. These are not supplied by the current release.
