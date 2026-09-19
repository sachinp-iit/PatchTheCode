# Security Policy

## Supported Versions

PatchTheCode is currently under active development. Security fixes are
prioritized for the latest version available on the default branch.

| Version | Supported |
| ------- | --------- |
| Latest / default branch | Yes |
| Older releases | Best effort |

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub issues.

If you discover a security vulnerability in PatchTheCode, please report it
privately to the project maintainer.

Include, where possible:

- A description of the vulnerability
- Steps to reproduce the issue
- The affected component or version
- Potential impact
- A proof of concept, if available
- Any suggested mitigation

Please avoid including secrets, credentials, production data, or other
sensitive information in the report.

The maintainer will acknowledge receipt and investigate the report. Once a fix
is available, the vulnerability may be disclosed publicly after reasonable
coordination with affected users and contributors.

## Security-Sensitive Areas

PatchTheCode may interact with production observability systems, source-code
repositories, CI/CD systems, communication platforms, and LLM providers.
Contributors should treat credentials, tokens, production data, source code,
logs, and generated patches as potentially sensitive.

Never commit secrets, API keys, access tokens, credentials, private keys, or
production data to the repository.
