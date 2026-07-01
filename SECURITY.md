# Security Policy

We take the security of super-hype seriously. This project handles OAuth tokens
and acts on people's social accounts, so responsible disclosure matters.

## Reporting a vulnerability

Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.

Instead, report them privately through GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/S1LV3RJ1NX/superHype/security) of the repository.
2. Click **Report a vulnerability** to open a private security advisory, or use
   this direct link: https://github.com/S1LV3RJ1NX/superHype/security/advisories/new

Please include:

- A description of the issue and its impact.
- Steps to reproduce, or a proof of concept.
- The affected version, commit, or component.
- Any suggested remediation, if you have one.

## What to expect

- We aim to acknowledge a report within a few business days.
- We will investigate, keep you updated on progress, and let you know when the
  issue is resolved.
- We will credit you in the advisory once a fix is released, unless you prefer to
  remain anonymous.

## Scope

Issues that are in scope include, but are not limited to:

- Authentication or authorization bypass (JWT handling, role checks, ownership).
- Token handling and encryption at rest.
- Server-side request forgery, injection, or leakage of secrets.
- Any way to publish or act on a LinkedIn account without the owner's consent.

Thank you for helping keep super-hype and its users safe.
