# CryptoRisk AI

CryptoRisk AI is an institutional-grade cryptocurrency intelligence and risk analysis platform. The engine synthesizes quantitative market metrics, smart contract security audits, historical drawdowns, and Google Gemini generative AI reasoning into a multi-pillar risk report for web3 assets.

---

## System Architecture

```
[ Web Client / Mobile UI ]
          │ (REST API / Bearer JWT / OAuth)
          ▼
┌────────────────────────────────────────────────────────┐
│                   Flask Application                    │
│                                                        │
│  ┌─────────────────┐             ┌──────────────────┐  │
│  │ Auth & History  │             │ Async Risk Engine│  │
│  │   Blueprints    │             │ Worker Pools     │  │
│  └────────┬────────┘             └────────┬─────────┘  │
└───────────┼───────────────────────────────┼────────────┘
            │                               │
    ┌───────┴────────┐       ┌──────────────┴──────────────┐
    ▼                ▼       ▼              ▼              ▼
[PostgreSQL]    [Google OIDC] [CoinGecko]  [GoPlus Security] [Google Gemini 2.5]
(Users, Jobs,   (Sign-In)     (Market &     (Contract Honeypot, (Risk Synthesis &
 History)                      Liquidity)    Tax, Blacklist)     Regime Modeling)
```

### Key Architectural Characteristics
- **Unified Service Architecture:** High-efficiency Flask backend serving both modular RESTful API endpoints and static SPA frontend.
- **Asynchronous Execution Pipeline:** Thread pool executors decouple compute-heavy multi-provider fetches from web request threads, returning immediate job IDs with polled progress updates.
- **Multi-Tier Fault Tolerance:** In-memory caching with graceful stale-snapshot fallbacks, automatic rate-limit cooldown management, and defensive parsing guarantees high uptime during external provider degraded states.
- **Strict Security & Authentication:** Passwords hashed with standard `bcrypt`, tamper-proof HS256 JWT sessions, Google OAuth 2.0 integration, and parameterized PostgreSQL queries via connection pooling.

---

## Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Frontend** | Vanilla JavaScript (ES Modules), Custom Modern CSS3 (Dark Luxury Theme), HTML5 |
| **Backend** | Python 3.14, Flask, Gunicorn (`gthread` async worker model) |
| **Database** | PostgreSQL with `psycopg2` Threaded Connection Pool & `pgcrypto` UUIDs |
| **Authentication** | JSON Web Tokens (`PyJWT`), Google OAuth 2.0 (`Authlib`), `bcrypt` |
| **Market Intelligence**| CoinGecko API (Demo / Pro) with optional CMC / Binance fallback |
| **Contract Security**| GoPlus Token Security API (EVM Chain Analysis) |
| **Generative AI** | Google Gemini API (`gemini-2.5-flash`) |

---

## Core Features

- **Multi-Pillar Risk Scoring:** Calculates composite risk index (0–100) combining Volatility, Liquidity, Market Sensitivity (Beta), and Smart Contract Integrity.
- **Contract Security Scanning:** Automatically analyzes EVM token contracts for honeypots, exorbitant buy/sell taxes, blacklisting capabilities, and ownership privileges via GoPlus.
- **Native Asset Awareness:** Automatically identifies Layer-1 native assets (BTC, ETH, SOL, AVAX, etc.) and adjusts audit criteria accordingly.
- **AI Executive Risk Synthesis:** Employs Google Gemini to analyze multi-source data and output structured executive summaries, risk regime assessments, and critical watch items.
- **Interactive Analysis History:** User analysis history is securely stored in PostgreSQL with collapsible inspection drawers and real-time live market updates.

---

## Project Structure

```
Crypto-Risk-AI/
├── app.py                   # Application factory & blueprint registration
├── config.py                # Environment configuration & provider settings
├── extensions.py            # DB connection pool, OAuth, and executor setup
├── pre_start.py             # Pre-deployment database migrations & schema setup
├── gunicorn.conf.py         # Production WSGI server configuration
├── render.yaml              # Render blueprint infrastructure configuration
├── requirements.txt         # Pinned Python production dependencies
├── .env.example             # Configuration template
├── routes/                  # Modular Flask blueprints
│   ├── auth.py              # Signup, login, Google OAuth, and JWT session handling
│   ├── dashboard.py         # Dashboard view and user summary endpoints
│   ├── health.py            # Health check, versioning, and provider status
│   ├── history.py           # Saved report lookup, deletion, and management
│   ├── market.py            # Live market snapshots and price queries
│   └── risk.py              # Synchronous & async job risk analysis endpoints
├── services/                # Business logic & external provider integrations
│   ├── analysis_worker.py   # Background job runner
│   ├── auth_service.py      # Password hashing, verification, & JWT decode
│   ├── coingecko.py         # CoinGecko client, caching, and rate limiting
│   ├── db_service.py        # Database queries & job lifecycle management
│   ├── goplus.py            # Smart contract token security analysis
│   └── risk_engine.py       # Quantitative math & AI synthesis orchestrator
├── static/                  # Static frontend assets
│   ├── style.css            # Dark mode design system
│   └── js/                  # ES modules (state, API clients, UI components)
├── templates/               # Jinja2 templates
│   ├── index.html           # Landing & authentication page
│   └── dashboard.html       # Analytics dashboard & interactive terminal
└── utils/                   # Helpers, mathematical algorithms, and error classes
```

---

## Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL database (local or cloud provider such as Supabase, Neon, or Render)
- Google Gemini API Key
- CoinGecko API Key (Demo or Pro)

### 1. Clone & Configure Environment

```bash
git clone https://github.com/chetanaybuilder/Crypto-Risk-AI.git
cd Crypto-Risk-AI
cp .env.example .env
```

Edit `.env` and provide your credentials:

```ini
FLASK_ENV=development
SECRET_KEY=your_secure_random_key
DATABASE_URL=postgresql://user:password@localhost:5432/cryptorisk
GEMINI_API_KEY=your_gemini_api_key
COINGECKO_API_KEY=your_coingecko_key
COINGECKO_PLAN=demo
```

### 2. Install Dependencies

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Initialize Database

Run the database migration and schema setup:

```bash
python pre_start.py
```

### 4. Run Development Server

```bash
python app.py
```

Navigate to `http://localhost:5000` in your browser.

---

## Production Deployment

### Deployment with Render Blueprint

This repository includes a `render.yaml` blueprint defining the web service, background task commands, and PostgreSQL database.

1. Connect your GitHub repository to Render.
2. Select **New > Blueprint** and link the repository.
3. In the Render service dashboard, supply secret environment variables (`GEMINI_API_KEY`, `COINGECKO_API_KEY`, and optional Google OAuth credentials).
4. Render will execute `python pre_start.py` before spawning the Gunicorn server via `gunicorn --config gunicorn.conf.py app:app`.

---

## License

MIT License. See `LICENSE` for details.
