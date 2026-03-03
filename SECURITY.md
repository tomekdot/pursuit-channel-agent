# Security Policy

## Scope

This policy applies to **ManiaPlanet Playlist Agent** and its production use in GitHub Actions.

## Supported Versions

Security fixes are provided for:

| Version | Supported |
| ------- | --------- |
| 1.x     | Yes       |
| < 1.0   | No        |

## Production Security Baseline

For production deployments:

1. Store credentials only in GitHub Actions Secrets (`MANIAPLANET_LOGIN`, `MANIAPLANET_PASSWORD`).
2. Do not hardcode credentials in code, workflow files, logs, or pull requests.
3. Keep workflow permissions minimal (`contents: read` unless more is required).
4. Keep dependencies updated and pin versions when possible.
5. Redact sensitive values in logs (enabled by default in this project).
6. Restrict repository admin access and require 2FA for maintainers.

## Reporting a Vulnerability

Please do **not** open a public issue for security vulnerabilities.

Use one of the private channels:

1. GitHub Security Advisories (preferred):
   - Repository -> Security -> Advisories -> New draft security advisory
2. Email: `tomaszkaczak@pm.me`

Include:

- affected version/commit
- reproduction steps or proof of concept
- impact assessment
- suggested mitigation (if available)

## Response Targets

- Acknowledgement: within 3 business days
- Triage update: within 7 business days
- Fix timeline: shared after triage based on severity

## Coordinated Disclosure

Please keep details private until a fix is released. We follow coordinated disclosure and publish advisories after remediation.
