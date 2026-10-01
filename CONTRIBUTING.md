# Contributing to Crypto-Risk-AI

First off, thank you for considering contributing to Crypto-Risk-AI! It's people like you that make open-source software such a great community to learn, inspire, and create.

## Getting Started

1. Fork the repository and create your branch from `main`.
2. Install dependencies: `pip install -r backend/requirements.txt` and `pip install -e .[dev]`
3. Ensure you have properly configured the `.env` file based on `.env.example`.
4. Make your changes.

## Code Style

- We use **Ruff** for Python linting and formatting, and **Black** for Python code formatting.
- For JavaScript and frontend assets, we use **ESLint** and **Prettier**.
- Before submitting your pull request, please run:
  ```bash
  ruff check .
  black .
  ```

## Testing

- Tests are located in the `tests/` directory.
- We use `pytest` for all unit and integration testing.
- Run tests locally before submitting a PR:
  ```bash
  pytest tests/
  ```

## Pull Request Process

1. Ensure your PR title follows conventional commits (e.g., `feat: added new risk factor`, `fix: patched JWT issue`).
2. Fill out the Pull Request template provided in the repository.
3. Your code must pass all CI checks before it can be merged.

Thank you!
