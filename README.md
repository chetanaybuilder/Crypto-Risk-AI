# 🛡️ CryptoRisk AI — Institutional Crypto Risk & Intelligence Terminal

[![Cloudflare Pages](https://img.shields.io/badge/Deployed%20on-Cloudflare%20Pages-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)](https://cryptorisk-ai.pages.dev)
[![Runtime](https://img.shields.io/badge/Runtime-Cloudflare%20Edge%20V8-0051C3?style=for-the-badge&logo=v8&logoColor=white)](https://cryptorisk-ai.pages.dev)
[![AI Engine](https://img.shields.io/badge/AI-Google%20Gemini%202.5%20Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev)
[![Smart Contract Security](https://img.shields.io/badge/Audits-GoPlus%20Security-20B2AA?style=for-the-badge)](https://gopluslabs.io)
[![License MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

> **Live Production Terminal:** [https://cryptorisk-ai.pages.dev](https://cryptorisk-ai.pages.dev)  
> Zero-downtime, serverless multi-pillar cryptocurrency risk scoring and AI intelligence engine deployed globally across 300+ edge locations.

---

## Executive Overview

**CryptoRisk AI** is an institutional-grade cryptocurrency intelligence terminal and automated quantitative risk engine. Built by veteran Web3 engineers, the platform synthesizes real-time order book liquidity, historical price volatility, benchmark market sensitivity ($\beta$), EVM bytecode smart contract security audits, and Google Gemini generative AI reasoning into a standardized, deterministic multi-pillar risk report ($0 - 100$ index).

The production system is deployed on **Cloudflare Pages** utilizing an **Advanced Mode Edge Worker (`_worker.js`)**, eliminating cold starts, third-party hosting bottlenecks, and dyno sleep cycles.

```
                      ┌─────────────────────────────────────────────────────────────┐
                      │              Cloudflare Anycast Global Edge                 │
                      │               https://cryptorisk-ai.pages.dev               │
                      └──────────────────────────────┬──────────────────────────────┘
                                                     │
                         ┌───────────────────────────┴───────────────────────────┐
                         ▼                                                       ▼
      ┌─────────────────────────────────────┐                 ┌─────────────────────────────────────┐
      │     Static Asset Distribution       │                 │       Cloudflare Edge Worker        │
      │           (Edge CDN)                │                 │             (_worker.js)            │
      ├─────────────────────────────────────┤                 ├─────────────────────────────────────┤
      │ • Landing View (index.html)         │                 │ • Multi-Pillar Quant Risk Engine    │
      │ • Terminal SPA (dashboard.html)     │                 │ • WebCrypto JWT Authentication      │
      │ • Modular ES Scripts (static/js/*)  │                 │ • Async Job Pipeline & Polling      │
      │ • Dark Luxury CSS (static/style.css)│                 │ • Live Market Telemetry In-Memory   │
      └─────────────────────────────────────┘                 └──────────────────┬──────────────────┘
                                                                                 │
                                     ┌───────────────────────────────────────────┼───────────────────────────────────────────┐
                                     ▼                                           ▼                                           ▼
                      ┌─────────────────────────────┐             ┌─────────────────────────────┐             ┌─────────────────────────────┐
                      │        CoinGecko API        │             │    GoPlus Security API      │             │    Google Gemini 2.5 AI     │
                      │   (Demo / Pro Market Data)  │             │   (EVM Smart Contract Audit)│             │ (Executive Risk Synthesis)  │
                      └─────────────────────────────┘             └─────────────────────────────┘             └─────────────────────────────┘
```

---

## Core Pillars of Quantitative Risk Scoring

The quantitative engine evaluates digital assets across four core risk dimensions, generating a standardized composite risk score from $0$ (lowest risk) to $100$ (critical risk):

### 1. Realized Volatility ($\omega_v = 0.30$)
Calculates the annualized sample standard deviation of continuous log-returns over a historical window:
$$\sigma_{\text{ann}} = \sqrt{365} \cdot \sqrt{\frac{1}{N-1} \sum_{i=1}^N \left( \ln\frac{P_i}{P_{i-1}} - \mu \right)^2}$$
- $\le 20\%$ annualized: **15 / 100** (Minimal Volatility)
- $\le 40\%$ annualized: **30 / 100** (Low Risk)
- $\le 60\%$ annualized: **50 / 100** (Moderate Risk)
- $\le 80\%$ annualized: **70 / 100** (Elevated Risk)
- $\le 120\%$ annualized: **85 / 100** (High Volatility)
- $> 120\%$ annualized: **95 / 100** (Extreme Tail Risk)

### 2. Secondary Market Liquidity ($\omega_l = 0.25$)
Evaluates trading velocity, order book depth, and 24-hour volume-to-market-cap turnover:
$$\text{Turnover Ratio} = \frac{\text{Volume}_{24\text{h}}}{\text{Market Cap}}$$
Penalizes illiquid micro-caps ($< \$1\text{M}$ volume) with immediate elevated risk classifications to protect portfolios from slippage and exit liquidity traps.

### 3. Market Sensitivity / Beta ($\omega_\beta = 0.20$)
Measures the directional covariance of asset returns relative to Bitcoin ($\text{BTC}$) as the market benchmark:
$$\beta = \frac{\text{Cov}(R_{\text{asset}}, R_{\text{BTC}})}{\text{Var}(R_{\text{BTC}})}$$
- $\beta < 0.8$: Low Market Beta (30)
- $0.8 \le \beta \le 1.3$: Moderate Market Sensitivity (48)
- $1.3 < \beta \le 1.8$: High Cyclical Beta (68)
- $\beta > 1.8$: Extreme Volatility Magnifier (85)

### 4. Smart Contract Security ($\omega_s = 0.25$)
Integrates directly with GoPlus EVM bytecode telemetry:
- **Honeypot Detection:** Automatic $100 / 100$ Critical Risk on verified bytecode sell restrictions.
- **Trading Tax Analysis:** Flags buy/sell extraction fees exceeding $10\%$.
- **Privilege Vectors:** Audits blacklist capabilities, un-capped minting functions, and owner balance manipulation.
- **Bytecode Verification:** Audits whether source code is verified on block explorers.
- **Layer-1 Native Assets:** Recognizes base Layer-1 assets (BTC, ETH, SOL, AVAX) and automatically marks contract attack surface as verified/NA.

### 5. Deterministic Stress Testing Engine
Every asset is subjected to simulated macro drawdowns:
1. **2020 Flash Crash (Black Thursday):** $-50\%$ systemic market liquidation.
2. **FTX Counterparty Insolvency:** $-28\%$ Tier-1 centralized exchange freeze.
3. **Terra / LUNA Depeg Contagion:** $-35\%$ decentralized liquidity run.
4. **Macro Yield Shock:** $+100\text{bps}$ interest rate surge rotation.

---

## Production Deployment: Cloudflare Pages

The project runs completely on **Cloudflare Pages** with an **Edge Worker gateway (`_worker.js`)**, providing:
- **Global Edge Execution:** Sub-10ms latency across 300+ data centers worldwide.
- **Unified Domain:** Frontend static SPA and RESTful APIs share the clean `pages.dev` origin.
- **Zero Cold Starts:** V8 isolates execute instantaneously with zero warm-up latency.
- **Zero Render Dependencies:** No reliance on sleeping dynos or fragile container hosts.

```bash
# Build production assets and bundle the Edge Worker
node build_cloudflare.js
node create_worker.js

# Deploy directly to Cloudflare Pages
wrangler pages deploy dist --project-name cryptorisk-ai --branch main
```

---

## RESTful Edge API Reference

### System Health
```http
GET /health
GET /api/health
```
**Response (200 OK):**
```json
{
  "success": true,
  "status": "healthy",
  "service": "CryptoRisk AI",
  "version": "3.2.0",
  "runtime": "Cloudflare Pages Edge Runtime (V8 Worker)",
  "gemini_configured": true,
  "coingecko_key_configured": true,
  "market_data_provider": "CoinGecko"
}
```

### Market Telemetry
```http
GET /api/market/:symbol
```
Retrieves real-time price, 24h change, volume, high/low, and market cap with edge caching.

### Asynchronous Risk Pipeline
```http
POST /api/analyze/start
POST /api/risk/start
Content-Type: application/json
Authorization: Bearer <token>

{
  "token_symbol": "ETH",
  "chain_id": "1",
  "contract_address": "0x..."
}
```
**Response (202 Accepted):**
```json
{
  "success": true,
  "job_id": "job_ETH_1_0x..._1793444336458_29a63dc8",
  "job": {
    "id": "job_ETH_1_0x..._1793444336458_29a63dc8",
    "token_symbol": "ETH",
    "status": "completed",
    "progress": 100
  }
}
```

### Job Status Polling
```http
GET /api/analyze/status/:jobId
GET /api/risk/job/:jobId
```
Returns completed status, quantitative pillars, stress test matrices, and the bespoke Gemini AI narrative.

### Synchronous Direct Risk Analysis
```http
POST /api/analyze
POST /api/risk/analyze
Content-Type: application/json
Authorization: Bearer <token>

{
  "token_symbol": "SOL"
}
```

### Authentication & Sessions
- `POST /api/auth/signup`: Registers user with WebCrypto PBKDF2 hashing + HS256 JWT.
- `POST /api/auth/login`: Verifies credentials and returns access token.
- `GET /api/auth/me`: Validates `Authorization: Bearer <token>` and returns profile.
- `GET /api/auth/google`: Initiates CSRF-protected Google OAuth 2.0 flow.
- `GET /api/auth/google/callback`: Validates OAuth code and state, redirects to `/dashboard#token=...`.
- `POST /api/auth/logout`: Graceful session termination.

### Dashboard & History
- `GET /api/dashboard`: Aggregates active user state, latest analysis, and history.
- `GET /api/history`: Retrieves authenticated user's analysis history list.
- `GET /api/history/:id`: Retrieves a single historical analysis record.
- `DELETE /api/history/:id`: Deletes single analysis record.
- `DELETE /api/history`: Clears authenticated user's analysis history.

---

## Repository Structure

```text
CryptoRisk-AI/
├── dist/                         # Compiled Cloudflare Pages distribution
│   ├── _worker.js                # Full-stack Cloudflare Edge Worker gateway
│   ├── _headers                  # Security & cache-control policies
│   ├── index.html                # Landing page SPA
│   ├── dashboard.html            # Intelligence terminal SPA
│   └── static/                   # Static CSS and ES modules
│       ├── style.css             # Dark luxury typography & responsive layout
│       └── js/                   # Vanilla ES modules (state, api, components)
│
├── backend/                      # Standalone Python Flask backend
│   ├── app.py                    # Application factory & blueprint gateway
│   ├── config.py                 # Provider keys & environment parameters
│   ├── extensions.py             # DB pool, OAuth, and thread executors
│   ├── requirements.txt          # Python production dependencies
│   ├── routes/                   # Modular Flask blueprints (auth, risk, market)
│   ├── services/                 # Risk engine, CoinGecko, GoPlus, Gemini AI
│   └── utils/                    # Math helpers, error models, telemetry
│
├── frontend/                     # Raw frontend source assets
│   ├── templates/                # Source HTML templates
│   └── static/                   # Source CSS and modular JavaScript
│
├── build_cloudflare.js           # Static asset compiler for Cloudflare Pages
├── create_worker.js              # Edge Worker compiler
├── app.py                        # Local development Python entrypoint
├── requirements.txt              # Root dependency manifest
└── .env.example                  # Environment configuration template
```

---

## Local Development

### 1. Python Local Backend
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Run local development server
python app.py
```
Visit `http://localhost:5000`.

### 2. Cloudflare Pages Local Development
```bash
# Build static assets & edge worker
node build_cloudflare.js
node create_worker.js

# Test locally with Wrangler
wrangler pages dev dist
```

---

## 🔒 Environment Variables Reference

| Variable | Description | Runtime |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Key for Google Gemini 2.5 Flash API | Cloudflare Secret & Python `.env` |
| `COINGECKO_API_KEY` | Key for CoinGecko Demo/Pro API | Cloudflare Secret & Python `.env` |
| `JWT_SECRET_KEY` / `JWT_SECRET` | Secret key for signing HS256 JWT tokens | Cloudflare Secret & Python `.env` |
| `GOOGLE_CLIENT_ID` | Google OAuth 2.0 Web Client ID | Cloudflare Secret & Python `.env` |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 Web Client Secret | Cloudflare Secret & Python `.env` |
| `SECRET_KEY` | Flask session secret key | Python `.env` |
| `DATABASE_URL` | PostgreSQL connection string | Python `.env` |

---

## ⚠️ Disclaimer

**Institutional Intelligence, Not Financial Advice.** This platform is designed solely to aggregate, model, and synthesize quantitative market risk data. Cryptocurrencies are highly volatile and inherently risky. Use at your own risk.

---

**Author:** [chetanaybuilder](https://github.com/chetanaybuilder)  
Institutional Proprietary / MIT License. Designed for quantitative digital asset risk management.
