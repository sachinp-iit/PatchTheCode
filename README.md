# PatchTheCode

> **AI Production Engineer for detecting, investigating, and fixing production issues.**

PatchTheCode connects your existing **observability systems, code repositories, CI/CD, and LLMs through MCP**. It detects production exceptions and warnings, investigates the evidence, identifies the affected service and repository, traces the issue to the relevant code, generates a fix, validates it, and opens a pull request for human review.

**Your infrastructure. Your repositories. Your models. One production engineering agent.**

---

## Why PatchTheCode?

Production debugging often means jumping between multiple systems:

```text
Alert
  ↓
Logs / Errors / Traces
  ↓
Deployment History
  ↓
Service
  ↓
Repository
  ↓
Source Code
  ↓
Root Cause
  ↓
Fix
  ↓
Tests / CI
  ↓
Pull Request
```

PatchTheCode brings this workflow together into one AI-driven investigation and remediation loop.

Instead of manually moving between tools:

```text
Production issue
      ↓
PatchTheCode
      ↓
Investigate evidence
      ↓
Find affected repository
      ↓
Identify root cause
      ↓
Generate fix
      ↓
Run validation
      ↓
Open PR
      ↓
Human review
```

PatchTheCode is designed to work **with your existing engineering infrastructure**, not replace it.

---

## How It Works

### 1. Detect

PatchTheCode reads production exceptions and warnings from connected MCP servers.

It can work with the observability systems already used by your organization.

### 2. Investigate

The agent gathers relevant evidence instead of blindly sending large volumes of raw logs to an LLM.

Investigation can include:

- Exception details
- Stack traces
- Error frequency
- Recent occurrences
- Deployment information
- Related events
- Service metadata
- Recent code changes
- Repository history

### 3. Discover the Repository

PatchTheCode can search connected code repositories through MCP to determine:

```text
Production issue
      ↓
Service
      ↓
Repository
      ↓
Branch / Commit
      ↓
File
      ↓
Function / Code path
```

This is particularly useful in environments with many services and repositories where the source repository is not known beforehand.

### 4. Determine Root Cause

The agent forms hypotheses from the available evidence and investigates the most relevant information.

The goal is not simply:

> "Here is an error."

It is:

> "Here is the production failure, the evidence connecting it to this code path, and the likely reason it is occurring."

### 5. Generate a Fix

When sufficient evidence exists, PatchTheCode can modify the relevant code in a controlled development context.

Production environments remain read-only during investigation.

### 6. Validate

The generated change can be validated through:

- Unit tests
- Integration tests
- Static checks
- Build checks
- Repository CI
- Other configured validation workflows

### 7. Open a Pull Request

PatchTheCode can create a PR containing:

- The proposed code change
- Root-cause explanation
- Production evidence
- Investigation context
- Validation results
- Relevant affected files

A human engineer remains in control of the final review and merge.

---

## Architecture

```text
                     ┌──────────────────────────┐
                     │      PatchTheCode        │
                     │                          │
                     │  Detection               │
                     │  Investigation           │
                     │  Repository Discovery    │
                     │  Root Cause Analysis     │
                     │  Code Modification       │
                     │  Validation              │
                     │  PR Generation           │
                     └────────────┬─────────────┘
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
                 ▼                ▼                ▼
        ┌────────────────┐ ┌───────────────┐ ┌───────────────┐
        │ Observability  │ │ Code / Git    │ │ CI / DevTools │
        │     MCPs       │ │     MCPs      │ │     MCPs      │
        └───────┬────────┘ └───────┬───────┘ └───────┬───────┘
                │                  │                 │
        Logs / Errors        Repositories       Tests / CI
        Events / Traces     Commits / PRs      Builds / Checks
        Deployments         Source Code
```

### Model Layer

PatchTheCode is designed to be **model agnostic**.

You can configure the LLMs appropriate for your environment rather than being locked into a single model provider.

The architecture can support different models for different tasks, such as:

```text
Investigation → Reasoning model
Code changes  → Coding model
Validation    → Test / review model
```

---

## MCP-Native

MCP is the integration boundary between PatchTheCode and your engineering systems.

This means PatchTheCode does not need to own your:

- Logs
- Error tracking
- Traces
- Source repositories
- CI/CD
- Developer communication
- LLM infrastructure

If your system exposes the capabilities PatchTheCode needs through MCP, it can potentially become part of the investigation workflow.

### Example MCP Connections

**Observability**

- Error tracking
- Log management
- Cloud logging
- APM
- Distributed tracing
- Monitoring

**Code**

- GitHub
- GitLab
- Bitbucket
- Internal Git systems

**Engineering**

- CI/CD
- Issue trackers
- Slack / Teams
- Deployment systems

> MCP is the integration layer. The core intelligence lives in PatchTheCode's investigation, evidence gathering, repository discovery, reasoning, remediation, and validation workflow.

---

## Example

Suppose production starts reporting:

```text
NullPointerException

PaymentService.processPayment()
PaymentService.java:184

Occurrences: 1,842
First seen: 10:32 UTC
Spike began after deployment: payments-api v2.8.4
```

PatchTheCode can investigate:

```text
Exception
   ↓
Payment Service
   ↓
Recent Deployment
   ↓
Repository Discovery
   ↓
PaymentService.java
   ↓
Relevant Code Path
   ↓
Recent Commit
   ↓
Root Cause Hypothesis
   ↓
Candidate Fix
   ↓
Tests
   ↓
Pull Request
```

The resulting PR can provide both the code change and the reasoning/evidence behind it.

---

## Safety & Human Review

PatchTheCode is designed around a **human-reviewed remediation workflow**.

The intended execution boundary is:

```text
Production
   │
   │ Read-only
   ▼
Investigation
   │
   ▼
Code Change
   │
   ▼
Tests / CI
   │
   ▼
Pull Request
   │
   ▼
Human Review
   │
   ▼
Merge / Deploy
```

PatchTheCode should not silently make irreversible production changes.

The final merge and production deployment remain subject to the team's existing engineering controls.

See [SECURITY.md](SECURITY.md) for security guidance.

---

## Project Status

🚧 **Early development**

PatchTheCode is being developed as an open-source AI Production Engineer.

The initial focus is:

- [x] MCP-first architecture
- [ ] Production exception and warning detection
- [ ] Exception fingerprinting and deduplication
- [ ] Evidence collection
- [ ] Automatic repository discovery
- [ ] Root-cause investigation
- [ ] AI-assisted code changes
- [ ] Automated validation
- [ ] Pull-request generation
- [ ] Developer notifications
- [ ] Investigation history
- [ ] Fix outcome feedback
- [ ] Learning from accepted/rejected fixes

Items marked as incomplete are part of the development roadmap and should not be interpreted as currently implemented functionality.

---

## Roadmap

### Phase 1 — Investigation

- MCP connector registry
- Exception normalization
- Fingerprinting and deduplication
- Evidence collection
- Investigation planner
- Root-cause analysis
- Repository discovery

### Phase 2 — Remediation

- Code modification
- Test selection
- Automated validation
- PR generation
- Investigation reports
- Slack / Teams notifications

### Phase 3 — Learning

- Fix outcome tracking
- Accepted/rejected fix feedback
- Investigation history
- Reusable debugging skills
- Production debugging playbooks
- Continuous improvement of investigation strategies

---

## Design Principles

### Bring Your Own Stack

PatchTheCode should work with the infrastructure you already operate.

### Evidence Before Action

The agent should gather relevant evidence before proposing or applying a code change.

### Read Production, Modify Development

Production is investigated through read access. Code changes happen in a controlled development workflow.

### Human Review

AI-generated fixes should pass through the organization's normal review and deployment process.

### Model Agnostic

The system should not depend on a single LLM provider.

### Explainable Remediation

A proposed fix should include the evidence and reasoning that led to it, together with validation results.

---

## Getting Started

> **Note:** PatchTheCode is currently under active development. Setup instructions will evolve as the first runnable release is published.

### Clone

```bash
git clone https://github.com/<your-org>/patchthecode.git
cd patchthecode
```

### Configure MCP

Configure the MCP servers that expose your observability and code systems.

A typical deployment may look like:

```text
PatchTheCode
    ├── Observability MCP
    ├── Git / Repository MCP
    ├── CI / Validation MCP
    └── Communication MCP
```

### Configure Your Model

Provide the LLM configuration required by your deployment.

PatchTheCode is intended to support configurable model providers rather than requiring a single provider.

### Run

Detailed installation and execution instructions will be added alongside the first stable runnable release.

---

## Repository Structure

The project is organized around the production debugging workflow:

```text
patchthecode/
├── agent/
├── investigation/
├── evidence/
├── repository/
├── remediation/
├── validation/
├── integrations/
├── mcp/
├── tests/
└── ...
```

The exact structure may evolve during early development.

---

## Contributing

Contributions are welcome.

Useful contributions include:

- MCP integrations
- Investigation strategies
- Repository discovery
- Evidence extraction
- Root-cause analysis
- Validation adapters
- Test integrations
- Developer workflows
- Security improvements
- Documentation

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Security

If you discover a security vulnerability, please do not open a public GitHub issue.

See [SECURITY.md](SECURITY.md) for the reporting process.

PatchTheCode may interact with production observability systems and source repositories. Treat credentials, tokens, source code, logs, and production data as sensitive.

---

## License

PatchTheCode is released under the **MIT License**.

See [LICENSE](LICENSE).

---

## Vision

PatchTheCode aims to move production debugging from:

> **"An engineer received an alert and now has to investigate everything manually."**

toward:

> **"An AI Production Engineer investigated the issue, found the relevant code, prepared a validated fix, and opened a PR for the engineer to review."**

**Detect. Investigate. Patch the code.**
