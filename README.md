# Budget Tracker

A local-first personal budgeting app for CSOB Slovakia CSV statements. It categorizes transactions with editable rules and tracks monthly spending, budgets, and savings goals. Your data stays on your computer.

## Requirements

Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js and npm. Install dependencies and build the frontend from the project root:

```sh
uv sync
cd web
npm ci
npm run build
cd ..
```

## Demo

The demo contains fictional transactions for September 2026. Use separate temporary copies of its editable settings:

```sh
mkdir -p /tmp/budget-tracker-demo
cp examples/demo/rules.yaml /tmp/budget-tracker-demo/rules.yaml
cp examples/demo/budgets.yaml /tmp/budget-tracker-demo/budgets.yaml
uv run python -m budget ui --data examples/demo --rules /tmp/budget-tracker-demo/rules.yaml --budgets /tmp/budget-tracker-demo/budgets.yaml --private /tmp/budget-tracker-demo/private.yaml
```

Open http://127.0.0.1:8000 and select September 2026. Rules and budgets edited in the UI are saved in the temporary demo directory. Re-run the copy commands to reset them.

## Your own statement

Export a CSV from CSOB Slovakia, place it in `data/`, and run:

```sh
uv run python -m budget ui
```

First copy `examples/demo/rules.yaml` to `rules.yaml` if you do not already have a rules file. The app reads CSV files from `data/`. Edit categorization rules in the UI and reload after adding statements. Keep exports, `rules.yaml`, `budgets.yaml`, `private.yaml`, keys and encrypted files private. Optional encryption commands are listed by `uv run python -m budget crypt --help`.

The backend listens on 127.0.0.1 and the UI uses relative API URLs. The Vite development server also binds to 127.0.0.1 and proxies API requests to the local backend. Installing dependencies requires internet access.

Run tests with `uv run pytest`.

## Roadmap

- Add a second bank's CSV importer behind the existing `budget/parsers/` boundary, mapping its fields into the same transaction format. A synthetic fixture should cover its headers, encoding, date and number formats, incoming and outgoing payments, and missing optional fields.
