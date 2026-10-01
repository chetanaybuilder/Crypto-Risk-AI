# Security Policy

## Supported Versions

Currently, only the `main` branch (latest release) is supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within Crypto-Risk-AI, please do not disclose it publicly. Instead, please send an email to the repository owner immediately.

We will review all reports and do our best to address the issue in a timely manner.

### Best Practices Enforced
- Do **not** commit `.env` or API keys to the repository.
- Parameterized SQL queries must be used at all times to prevent SQL injection.
- JWTs must be signed securely with an unpredictable `JWT_SECRET_KEY`.
- External API calls (CoinGecko, GoPlus) must utilize secure HTTPS connections and enforce timeout constraints.
