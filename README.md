# CryptoRisk AI

CryptoRisk AI is a production-grade, full-stack intelligence platform that transforms raw cryptocurrency tickers into structured, AI-powered risk assessment reports. Built for high-frequency market participants and researchers, the application cuts through market hype by synthesizing complex uncertainty, downside risks, and actionable signals into an executive-level format.

---

## Architecture & System Design

The platform uses a decoupled architecture separating high-performance static delivery from containerized server-side processing and cloud database persistence:

[ Netlify Static CDN ] --(HTTPS / OAuth)--> [ Render Python/Flask Backend ]
                                                    |
                                      +-------------+-------------+
                                      |                           |
                            [ Google Gemini API ]      [ Supabase PostgreSQL ]

* **Frontend Layer:** Built with tactile brutalism UI principles, clean CSS variables, and native responsive design, hosted globally via Netlify.
* **Backend Layer:** Powered by Python 3.14 and Flask, managing secure user sessions, CSRF protections, and OAuth verification via Authlib.
* **Intelligence Layer:** Integrates the Google Gemini API to analyze cryptocurrency tickers under strict data policies, filtering out real-time price hallucination in favor of rigorous risk analysis.
* **Data Layer:** Persistent relational storage managed via PostgreSQL (Supabase / Render), maintaining strict foreign-key constraints between authenticated users and their historical analysis reports.

---

## Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Frontend** | HTML5, Modern CSS3, JavaScript (ES6+) |
| **Backend** | Python, Flask, Gunicorn |
| **Authentication** | Google OpenID Connect (OAuth 2.0 via Authlib) |
| **AI Engine** | Google Gemini API (`gemini-2.5-flash`) |
| **Database** | PostgreSQL, Psycopg2 (Supabase / Render Hosting) |
| **Deployment** | Netlify (Static Hosting) & Render (Web Service Container) |

---

## Core Features

* **Secure Authentication:** Frictionless Google OAuth login ensuring verified identity mapping and session safety.
* **Structured Risk Engine:** Generates uniform JSON schemas evaluating asset trends, risk scores, core problems solved, and exact counts of key risks, signals, and watch items.
* **Persistent User History:** Automatically serializes generated reports to a secure relational database indexed by user identification.
* **Defensive Error Handling:** Built-in mitigation for API quota exhaustion (`RESOURCE_EXHAUSTED`), malformed JSON recovery, and robust input sanitization.

---

## Project Structure

Crypto-Risk-AI/
├── backend/
│   ├── app.py              # Main Flask application and API integration
│   ├── requirements.txt    # Python runtime dependencies
│   └── templates/          # Jinja templates (dashboard and reports)
├── frontend/
│   ├── index.html          # Landing page (Netlify deployment)
│   ├── dashboard.html      # Client-side user interface
│   └── style.css           # Global design system & tactile styles
└── README.md

---

## Environment Variables

To run or deploy this project locally, configure the following environment variables in your environment or `.env` file:

SECRET_KEY=your_flask_session_secret
DATABASE_URL=postgresql://user:password@host:port/dbname
GEMINI_API_KEY=your_google_gemini_api_key
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret

---

## Local Development & Setup

1. **Clone the repository:**
   git clone https://github.com/chetanaybuilder/Crypto-Risk-AI.git
   cd Crypto-Risk-AI

2. **Set up the backend environment:**
   cd backend
   pip install -r requirements.txt

3. **Run the Flask application:**
   python app.py

4. **Access the platform:**
   Navigate to `http://localhost:5000` in your browser.
