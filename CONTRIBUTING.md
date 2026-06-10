# Contributing to AlphaStratum

## Workflow

1. Fork the repo and create a feature branch
2. Make your changes
3. Open a Pull Request

## Before Submitting

- Run `npm run build` in `nextjs-app/` — it must pass with no errors
- Run `python -c "from routers.models import *"` in `fastapi-backend/` — no import errors
- Do **not** commit any secrets or API keys — use the `.env.example` templates instead

## Code Style

- Follow the existing patterns in the codebase (naming, structure, comments)
- Keep functions small and focused
- Add inline comments for non-obvious quantitative logic

## API Keys & Secrets

All sensitive configuration goes in `.env` files (backend) and `.env.local` (frontend). The `.env.example` and `.env.local.example` files document all required variables. **Never hardcode secrets in source files.**

## Tests

Tests are not required for MVP contributions, but are appreciated for new model endpoints.

## Licensing

By submitting a PR, you agree that your contribution will be licensed under the AGPL-3.0 license.
