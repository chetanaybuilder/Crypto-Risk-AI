# 🚀 CryptoRisk AI

AI-powered cryptocurrency risk intelligence platform built with **Python, Flask, PostgreSQL, and Google Gemini AI**.

CryptoRisk AI enables users to securely analyze cryptocurrency assets, receive AI-generated market insights, and maintain a personal history of predictions through a clean web dashboard.

---

## 🌐 Live Demo

https://crypto-risk-ai-2.onrender.com

---

## 📸 Screenshots

### Landing Page

![Landing Page](screenshots/landing.png)

### Login Page

![Login Page](screenshots/login.png)

### Register Page

![Register Page](screenshots/register.png)

### Dashboard

![Dashboard](screenshots/dashboard.png)

### AI Analysis

![AI Analysis](screenshots/analysis.png)

### Prediction History

![Prediction History](screenshots/history.png)


---

# ✨ Features

- 🔐 Secure User Authentication
- 🤖 AI-Powered Cryptocurrency Analysis
- 📈 Market Trend Prediction
- ⚠️ AI Risk Assessment
- 💰 Predicted Price Estimation
- 📝 Professional Market Summary
- 📊 Prediction History Dashboard
- 🔒 Password Hashing
- 💾 PostgreSQL Database Storage
- 🔑 Environment Variable Security
- 📱 Responsive Dark UI

---

# 🛠 Tech Stack

## Backend

- Python
- Flask

## Frontend

- HTML5
- CSS3

## Artificial Intelligence

- Google Gemini 2.5 Flash API

## Database

- PostgreSQL

## Authentication

- Flask Sessions
- Werkzeug Password Hashing

## Deployment

- Render

---

# 📂 Project Structure

```text
crypto-risk-ai/

│── app.py
│── requirements.txt
│── README.md
│── .gitignore
│── .env

├── instance/
│ └── crypto.db

├── static/
│ └── style.css

└── templates/
├── index.html
├── login.html
├── register.html
└── dashboard.html
```

---

# ⚙️ Installation

Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/crypto-risk-ai.git
```

Move into the project

```bash
cd crypto-risk-ai
```

Install dependencies

```bash
pip install -r requirements.txt
```

Create a `.env` file

```env
SECRET_KEY=your_secret_key
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://username:password@host:port/database
```

Instead of creating `.env` from scratch, copy the example and fill values:

```bash
cp .env.example .env
# then edit `.env` and DO NOT commit it to Git
```

Ensure `.env` is listed in `.gitignore` so secrets are not pushed to GitHub.

Run the application

```bash
python app.py
```

---

## Render Deployment

This project includes `render.yaml` and `Procfile` for deployment on Render.

1. Create a new Python Web Service on Render.
2. Connect your GitHub repository and choose the `main` branch.
3. Add environment variables: `SECRET_KEY`, `GEMINI_API_KEY`, and `DATABASE_URL`.
4. Render will build with `pip install -r requirements.txt` and start with `gunicorn app:app --bind 0.0.0.0:$PORT`.


# 🚀 Future Improvements

- Live cryptocurrency market data (CoinGecko API)
- Interactive price charts
- PostgreSQL database
- Docker support
- JWT Authentication
- REST API
- Portfolio Tracking
- Watchlist
- Admin Dashboard
- CI/CD Pipeline

---

⚠️ Demo Environment

This project is built for Render with PostgreSQL. Use a managed PostgreSQL service or Render Postgres database and set `DATABASE_URL` to keep users and history persistent.

• Registration and login are fully functional.
• AI cryptocurrency analysis works normally.
• Prediction history and user accounts are stored in PostgreSQL.


# 📜 License

This project is licensed under the MIT License.

---

# 👨‍💻 Developer

**Chetanay Batra**

AI Developer focused on building production-ready AI-powered SaaS applications using Python and modern web technologies.
