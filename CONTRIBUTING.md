# Contributing to AlphaStratum

## Workflow

1. Fork the repo and create a feature branch
2. Make your changes
3. Open a Pull Request (CI runs on every PR)

## Before Submitting

All of these are enforced by CI — they must pass locally first:

**Backend** (from `fastapi-backend/`, in a venv):

```bash
pip install -r requirements-dev.txt
ruff check .
python -m pytest
```

**Frontend** (from `nextjs-app/`):

```bash
npm ci
npm run typecheck   # tsc --noEmit
npm run lint        # next lint
npm test            # vitest
npm run build       # runs typecheck + lint again
```

- Do **not** commit any secrets or API keys — use the `.env.example` templates instead

## Code Style

- Backend: `ruff` (config in `fastapi-backend/pyproject.toml`, 110-char lines); line-length and import order are checked
- Frontend: TypeScript strict mode and `eslint-config-next`; no `any` types in new code
- Follow the existing patterns in the codebase (naming, structure, comments)
- Keep functions small and focused; quant math lives in `fastapi-backend/services/quant.py` as pure functions
- Add inline comments for non-obvious quantitative logic

## API Keys & Secrets

All sensitive configuration goes in `.env` files (backend) and `.env.local` (frontend). The `.env.example` and `.env.local.example` files document all required variables. **Never hardcode secrets in source files.**

## Tests

Tests are required for backend model endpoints and frontend logic changes:

- New pure quant functions belong in `services/quant.py` with tests in `tests/test_quant.py`
- Endpoint behavior (success/validation/error shapes) in `tests/test_api_*.py` with monkeypatched market data — tests must stay hermetic (no network, no DB)
- Frontend logic lives in `lib/` modules with tests in `__tests__/`

## Licensing

By submitting a PR, you agree that your contribution will be licensed under the AGPL-3.0 license.
