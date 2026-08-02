# AGENTS.md

Coding agent guidance for PrintGuard lives in **[CLAUDE.md](CLAUDE.md)**, the single source of
truth for commands, architecture and the project's conventions. Read it first.

Two rules from it that are easy to skip and expensive to miss:

- **Documentation is part of every change.** If a change touches something the docs describe,
  update those pages in the same change, and delete what the change makes wrong. CLAUDE.md
  has the map of which page covers what.
- **English, and never an em dash** in docs, changelog entries, commit messages or UI
  copy. Everything published, including PR descriptions and issue comments, is written in the
  first person as the maintainer, not in an assistant's voice.

Deeper references: [docs/README.md](docs/README.md) indexes the documentation set;
[docs/architecture.md](docs/architecture.md) covers the engine, the `Platform` contract,
scheduling and the fail-safe design; [docs/api.md](docs/api.md) covers the hub's REST API and
MCP server; [CONTRIBUTING.md](CONTRIBUTING.md) has dev setup, the release cycle and
step-by-step guides for adding a printer integration or notification provider.
