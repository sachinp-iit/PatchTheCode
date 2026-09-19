# Contributing to PatchTheCode

Thank you for contributing to PatchTheCode.

PatchTheCode is an open-source AI Production Engineer focused on detecting,
investigating, and fixing production issues through MCP-connected systems.

## Getting Started

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Add or update tests where appropriate.
5. Run the project's validation and test suite.
6. Open a pull request with a clear description of the change.

## Pull Requests

A good pull request should:

- Explain what changed and why.
- Keep the scope focused.
- Include tests for new behavior where practical.
- Avoid unrelated formatting or refactoring.
- Document configuration or behavioral changes.
- Clearly identify security-sensitive changes.

For larger architectural changes, open an issue first so the design can be
discussed before substantial implementation work begins.

## Code Quality

Contributions should prioritize:

- Correctness
- Security
- Maintainability
- Clear interfaces
- Good error handling
- Testability
- Minimal unnecessary complexity

## MCP Integrations

When adding an MCP integration:

- Clearly document the required tools and permissions.
- Avoid requesting broader permissions than necessary.
- Do not expose secrets in logs or error messages.
- Document destructive or write-capable operations.
- Prefer read-only access during investigation whenever possible.

## AI / Agent Behavior

Changes affecting agent behavior should include enough information to
understand:

- What evidence the agent uses.
- What actions it can take.
- What happens when evidence is insufficient.
- What safety or confidence gates exist.
- Whether the behavior can modify repositories or create external side effects.

Avoid designs that silently make irreversible production changes.

## Tests

Run the relevant tests and checks before opening a pull request.

If a test cannot be run locally, explain why in the pull request.

## Licensing

By contributing to PatchTheCode, you agree that your contributions are
provided under the project's MIT License, subject to the terms of that
license.

You retain copyright in your contributions unless you explicitly transfer it
under a separate agreement.

## Community

Please keep discussions constructive and technical. Contributions should focus
on improving PatchTheCode and its ecosystem.
