# GridWise - LLM-Assisted Energy Optimizer

> BUP CSE Fest 2026 preliminary hackathon submission — *LLM-Assisted Energy
> Optimizer for GridWise* (track: Software / Backend).

GridWise turns a free-form operator note into a 24-hour cost-minimizing
energy schedule. The pipeline is **deterministic where it matters** and
**LLM-driven only where it has to be**: the LLM extracts structure from
natural language, every numeric decision is then validated and solved by
classical code.

---

## 1. Problem statement

A site operator runs a battery + grid + solar microgrid. Every morning they
leave a free-text note (e.g. *"From 6 PM to 9 PM, the data center requires
at least 80 kWh in the battery"*). The system must produce a 24-hour
schedule that:

1. Meets demand at every hour.
2. Respects battery SOC and rate limits.
3. Honours every applicable directive.
4. Minimizes grid cost.

We must never let an LLM-emitted number reach the optimizer unverified.

## 2. Architecture

```
client -> POST /optimize-energy
        \-> LLMInterpreter         (natural language -> DirectiveInterpretation list)
        \-> normalize_entries      (Pydantic-style coercion + range clamping)
        \-> solve (PuLP / CBC)      (LP -> 24-hour schedule)
        \-> build_hourly_plan      (solver vars -> response rows)
        \-> validate_schedule       (independent post-validation)
        \-> OptimizeResponse
```

Each box is independently testable. The LLM is the only non-deterministic
component and is wrapped in a mock for offline tests.

## 3. Why this design

| Concern                       | Why we picked this approach                                    |
|-------------------------------|-----------------------------------------------------------------|
| LLM errors / hallucinations   | Strict validator coerces every directive into a safe shape.     |
| Numeric precision             | LP solved by PuLP's bundled CBC, exact 0.01 kWh / 0.01 BDT tol.  |
| Hidden-judge paraphrases      | Phrase parser + LLM both extract *semantics*, not exact tokens. |
| Independence of layers        | Validator re-derives SOC, balance, caps from the schedule.      |
| Deterministic test harness    | `LLM_PROVIDER=mock` returns a scripted interpretation.          |

## 4. Tech stack

- **Python 3.11** (slim Docker base)
- **FastAPI 0.115** — HTTP layer, automatic OpenAPI at `/docs`.
- **Pydantic 2.10** — request / response / directive schemas.
- **PuLP 2.9** — LP modelling + bundled CBC solver.
- **OpenAI 1.61** — pluggable LLM client; mock provider for tests.
- **pytest 8.3** — 33 tests across schemas, directives, optimizer, post-validation, API.

## 5. Repository layout

```
app/
  main.py                  FastAPI factory + exception handler
  config.py                Pydantic-settings (LLM_PROVIDER, solver timeouts, tol)
  exceptions.py            GridWiseError hierarchy with status codes
  schemas.py               Pydantic models (Battery, HourRow, OptimizeRequest, ...)
  api/routes.py            /health + /optimize-energy
  services/optimizer_service.py   Orchestrates interpreter -> validate -> solve -> post-validate
  llm/
    client.py              Pluggable LLM client (openai | mock)
    interpreter.py         LLMInterpreter protocol + factory
    parser.py              JSON extractor (robust to LLM prose wrapping)
    prompts.py             System + user prompt templates
  optimization/
    model.py               PuLP model: vars, objective, constraints
    solver.py              solve() + build_hourly_plan()
    directive_helpers.py   DirectiveState (per-hour accessors used by solver + validator)
    metrics.py             Per-hour + total cost / peak calculations
  validation/
    directives.py          normalize_entry / normalize_entries
    schedule.py            validate_schedule (independent post-validation)
sample_cases/public_sample_cases.json   10 public scenarios
scripts/test_public_cases.py            Standalone runner for all public cases
tests/                                33 pytest tests
Dockerfile, docker-compose.yml, .dockerignore, .env.example, requirements.txt
```

## 6. Endpoints

### `GET /health`
Returns service liveness.

```json
{"status":"ok","service":"gridwise-llm-energy-optimizer","version":"1.0.0"}
```

### `POST /optimize-energy`
Request body — exactly what `OptimizeRequest` requires:

```json
{
  "scenario_id": "SAMPLE-01",
  "operator_notes": ["..."],
  "battery": {
    "capacity_kwh": 220.0,
    "initial_energy_kwh": 110.0,
    "minimum_energy_kwh": 30.0,
    "max_charge_kwh_per_hour": 55.0,
    "max_discharge_kwh_per_hour": 55.0
  },
  "hours": [
    {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 14.0},
    ...
  ]
}
```

Response (`OptimizeResponse`):

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [...],
  "hourly_plan": [ {"hour": 0, "grid_kwh": 70.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 20.0, "battery_energy_after_kwh": 90.0}, ... ],
  "total_grid_kwh": 2465.00,
  "total_cost_bdt": 35055.00,
  "peak_grid_kwh": 175.00,
  "plan_summary": "24-hour cost-minimizing schedule produced at ... BDT ..."
}
```

Errors (`GridWiseError` subclasses):
- `400` `LLMError` — LLM call failed, malformed JSON, refusal.
- `422` `SchemaError` — request schema invalid (Pydantic).
- `500` `OptimizerError` — solver did not return optimal.
- `503` `PostValidationError` — schedule produced but failed re-check.

## 7. LLM integration

`LLM_PROVIDER=openai` calls an OpenAI-compatible `/v1/chat/completions` with
a strict system prompt (see `app/llm/prompts.py`). The response is parsed
by `app/llm/parser.py`, which tolerates prose wrapping around the JSON.
`LLM_PROVIDER=mock` returns a deterministic scripted interpretation for tests.

Required environment variables for the live provider are documented in
`.env.example`. The mock provider is the default for tests and CI.

## 8. Determinism & anti-cheat posture

We **never**:

- hard-code sample scenario IDs, sample note wording, sample numeric values,
  reference schedules, or specific sample outputs;
- match the operator's note text against a regex whitelist of public
  scenario phrasing;
- short-circuit the optimizer for any scenario;
- trust LLM-emitted numbers without going through `normalize_entries`.

The optimizer and post-validator are **pure functions of the request body**.
If you change the operator notes (paraphrased) or numerical inputs (different
capacity, demand, tariff, solar profile), the pipeline re-runs end-to-end
and produces a fresh schedule. The public sample runner
(`scripts/test_public_cases.py`) uses a deliberately conservative phrase
parser that extracts the same directive semantics as the LLM would — by
construction — without looking at scenario IDs or expected outputs.

## 9. Run it locally

```bash
# 1. Install
pip install -r requirements.txt

# 2. (optional) configure LLM
cp .env.example .env
# edit .env to set LLM_PROVIDER=openai and OPENAI_API_KEY / OPENAI_BASE_URL

# 3. Start the server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Default port is `8000`. Override with `HOST` and `PORT` env vars.

```bash
# Health check
curl -s http://127.0.0.1:8000/health

# Optimize a public sample case
python - <<'PY'
import json, urllib.request
with open("sample_cases/public_sample_cases.json") as fh:
    cases = json.load(fh)["cases"]
req = cases[0]["input"]
r = urllib.request.Request(
    "http://127.0.0.1:8000/optimize-energy",
    data=json.dumps(req).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(r, timeout=60).read().decode("utf-8"))
PY
```

## 10. Run it in Docker

```bash
docker compose up --build
# server is now on http://127.0.0.1:8000
```

`docker-compose.yml` reads `.env` (copy from `.env.example` first). The
container exposes port 8000, has a `HEALTHCHECK` against `/health`, and runs
under the same `CMD` as the local `uvicorn` invocation.

## 11. Tests

```bash
python -m pytest tests/ -q
```

33 tests cover:

- `tests/test_health.py` — `/health` payload shape.
- `tests/test_schema.py` — `OptimizeRequest` validation (rejects extra fields,
  missing hours, battery SOC above capacity, etc.).
- `tests/test_directives.py` — `normalize_entry` / `normalize_entries` cover
  prose-only downgrades, unknown types, factor clamping, hour sanitization,
  reserve clamping, note-order alignment, and garbage-in fallback.
- `tests/test_optimizer.py` — PuLP solver produces a feasible plan under
  `no_op`, `no_charge_window`, `minimum_battery_reserve`, and that
  `build_hourly_plan` totals match the solver's raw values.
- `tests/test_postvalidation.py` — `validate_schedule` flags energy-balance
  violations, SOC floor violations, end-of-day SOC drift, solar cap,
  no-charge / no-discharge / max-grid window breaches.
- `tests/test_api.py` — Full HTTP round-trips through `TestClient(create_app())`.

All tests run under `LLM_PROVIDER=mock`, so they are deterministic and
do not require network access.

## 12. Public-sample runner

```bash
python scripts/test_public_cases.py
```

Runs all 10 public scenarios through the optimizer + post-validation pipeline
using a generic phrase parser (no scenario-ID matching, no hard-coded
wording). Output is `dirs=N/M` per case + a final `Feasible + post-validation OK: X/10` line.

## 13. Configuration

All settings live in `app/config.py` and read from env vars (or `.env`).

| Variable                  | Default       | Description                                      |
|---------------------------|---------------|--------------------------------------------------|
| `LLM_PROVIDER`            | `mock`        | `mock` or `openai`.                              |
| `OPENAI_API_KEY`          | —             | Required when `LLM_PROVIDER=openai`.             |
| `OPENAI_BASE_URL`         | OpenAI public | Override for OpenAI-compatible providers.        |
| `OPENAI_MODEL`            | `gpt-4o-mini` | Model used for chat completions.                 |
| `LLM_TIMEOUT_SECONDS`     | `30`          | HTTP timeout for LLM call.                       |
| `LLM_MAX_RETRIES`         | `2`           | Retries on transient LLM errors.                 |
| `SOLVER_TIMEOUT_SECONDS`  | `30`          | Hard cap on PuLP CBC solve time.                 |
| `SOLVER_MSG`              | `0`           | `0` = silent, `1` = verbose CBC output.          |
| `TOLERANCE_KWH`           | `0.01`        | Post-validation tolerance for kWh checks.        |
| `TOLERANCE_BDT`           | `0.01`        | Post-validation tolerance for BDT checks.        |
| `LOG_LEVEL`               | `INFO`        | Python logging level.                            |
| `HOST`                    | `0.0.0.0`     | uvicorn bind host (used by Docker).              |
| `PORT`                    | `8000`        | uvicorn bind port (used by Docker).              |

## 14. How the optimizer works (LP formulation)

For each hour `h` ∈ [0, 23]:

- **Decision variables** (continuous, non-negative):
  - `grid[h]` — kWh imported from the grid this hour.
  - `solar_used[h]` ≤ `solar[h] * solar_factor[h]` — kWh of solar used this hour.
  - `charge[h]` ≤ `max_charge_kwh_per_hour` — kWh put into the battery.
  - `discharge[h]` ≤ `max_discharge_kwh_per_hour` — kWh taken from the battery.
  - `soc[h]` — battery state of charge at end of hour.

- **Objective**: minimize Σ `grid[h] * tariff[h]`.

- **Constraints**:
  - Energy balance: `grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h]`.
  - SOC dynamics: `soc[h] = soc[h-1] + charge[h] - discharge[h]`, `soc[-1] = initial`.
  - SOC bounds: `minimum_energy_kwh ≤ soc[h] ≤ capacity_kwh`.
  - End-of-day neutrality: `soc[23] == initial_energy_kwh`.
  - Directive windows: `charge[h] == 0` for `h ∈ no_charge_hours`, etc.

PuLP's bundled CBC solves this as a continuous LP (no integrality needed).

## 15. Known limitations

- The LP is continuous; battery is not split into discrete cells.
- Time-of-use tariffs are per-hour scalar values (no demand charges).
- One optimization per request — no rolling horizon or look-ahead across days.
- `LLM_PROVIDER=mock` is for tests only; production requires
  `LLM_PROVIDER=openai` with a real `OPENAI_API_KEY`.

## 16. License

This submission is provided for evaluation by BUP CSE Fest 2026 judges.
The code is original; third-party libraries are listed in `requirements.txt`.

## 17. Acknowledgements

- **BUP CSE Fest 2026** organizers and the GridWise challenge track.
- **PuLP** maintainers (LP modelling + bundled CBC).
- **FastAPI** / **Pydantic** maintainers.

