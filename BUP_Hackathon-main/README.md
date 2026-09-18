# GridWise — LLM-Assisted Energy Optimizer

> **BUP CSE Fest 2026 — Preliminary Hackathon Submission**
> Track: Software / Backend

A free-form operator note goes in. A validated, cost-minimal 24-hour energy schedule comes out.

The design rule is simple: **the LLM reads language, classical code decides numbers.** No value emitted by a model reaches the optimizer without passing through a strict normalizer first.

---

## Table of contents

1. [Quickstart](#1-quickstart)
2. [The problem](#2-the-problem)
3. [Pipeline at a glance](#3-pipeline-at-a-glance)
4. [Design rationale](#4-design-rationale)
5. [Tech stack](#5-tech-stack)
6. [API reference](#6-api-reference)
7. [LLM integration](#7-llm-integration)
8. [Determinism & anti-cheat posture](#8-determinism--anti-cheat-posture)
9. [The LP formulation](#9-the-lp-formulation)
10. [Testing](#10-testing)
11. [Configuration reference](#11-configuration-reference)
12. [Repository layout](#12-repository-layout)
13. [Known limitations](#13-known-limitations)
14. [License & acknowledgements](#14-license--acknowledgements)

---

## 1. Quickstart

### Option A — local Python

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (optional) configure a live LLM provider
cp .env.example .env
#    then set LLM_PROVIDER=openai and OPENAI_API_KEY / OPENAI_BASE_URL

# 3. Run
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Option B — Docker

```bash
cp .env.example .env
docker compose up --build
```

Either way the service listens on **http://127.0.0.1:8000** (override with `HOST` / `PORT`).
Interactive OpenAPI docs are served at **`/docs`**.

### Smoke test

```bash
curl -s http://127.0.0.1:8000/health
```

```bash
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

The Docker image carries a `HEALTHCHECK` against `/health` and boots with the same uvicorn
command as the local run, so the two paths are behaviourally identical.

---

## 2. The problem

A site operator runs a microgrid: **battery + grid import + solar**. Each morning they leave a
plain-language note, for example:

> *"From 6 PM to 9 PM, the data center requires at least 80 kWh in the battery."*

From that note plus 24 hours of demand / solar / tariff data, the service must return a schedule that:

- **meets demand** at every single hour,
- **respects** battery state-of-charge floors, capacity, and charge/discharge rate limits,
- **honours every applicable directive** extracted from the note,
- **minimizes total grid cost**.

The hard part is not the optimization — it is making sure a hallucinated number never becomes a
constraint.

---

## 3. Pipeline at a glance

```text
POST /optimize-energy
        │
        ├─▶ LLMInterpreter        natural language ──▶ DirectiveInterpretation[]
        ├─▶ normalize_entries     coercion, clamping, note-order alignment
        ├─▶ solve (PuLP / CBC)    LP ──▶ 24-hour schedule
        ├─▶ build_hourly_plan     solver vars ──▶ response rows
        ├─▶ validate_schedule     independent re-derivation of every number
        └─▶ OptimizeResponse
```

Every stage is a pure, independently testable unit. The interpreter is the only non-deterministic
component in the chain, and it is swappable for a scripted mock.

---

## 4. Design rationale

| Concern | How it is handled |
| --- | --- |
| LLM errors / hallucinations | A strict validator coerces every directive into a safe shape before use. |
| Numeric precision | LP solved by PuLP's bundled CBC, with 0.01 kWh / 0.01 BDT tolerances. |
| Hidden-judge paraphrases | Both the phrase parser and the LLM extract *semantics*, never exact tokens. |
| Layer independence | The post-validator re-derives SOC, balance and caps from the returned schedule alone. |
| Deterministic tests | `LLM_PROVIDER=mock` returns a scripted interpretation — no network needed. |

---

## 5. Tech stack

| Component | Version | Role |
| --- | --- | --- |
| Python | 3.11 (slim Docker base) | Runtime |
| FastAPI | 0.115 | HTTP layer, automatic OpenAPI at `/docs` |
| Pydantic | 2.10 | Request / response / directive schemas |
| PuLP | 2.9 | LP modelling + bundled CBC solver |
| OpenAI SDK | 1.61 | Pluggable LLM client (mock provider for tests) |
| pytest | 8.3 | 33 tests across schemas, directives, optimizer, validation, API |

---

## 6. API reference

### `GET /health`

Liveness probe.

```json
{
  "status": "ok",
  "service": "gridwise-llm-energy-optimizer",
  "version": "1.0.0"
}
```

### `POST /optimize-energy`

**Request** — exactly the fields `OptimizeRequest` requires:

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
    {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 14.0}
  ]
}
```

**Response** — `OptimizeResponse`:

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 70.0,
      "solar_used_kwh": 0.0,
      "battery_action": "discharge",
      "battery_kwh": 20.0,
      "battery_energy_after_kwh": 90.0
    }
  ],
  "total_grid_kwh": 2465.00,
  "total_cost_bdt": 35055.00,
  "peak_grid_kwh": 175.00,
  "plan_summary": "24-hour cost-minimizing schedule produced at ... BDT ..."
}
```

**Error contract** — every failure is a `GridWiseError` subclass with a fixed status code:

| Status | Exception | Meaning |
| --- | --- | --- |
| 400 | `LLMError` | LLM call failed, returned malformed JSON, or refused |
| 422 | `SchemaError` | Request schema invalid (Pydantic) |
| 500 | `OptimizerError` | Solver did not reach an optimal solution |
| 503 | `PostValidationError` | A schedule was produced but failed the independent re-check |

---

## 7. LLM integration

With `LLM_PROVIDER=openai`, the service calls an OpenAI-compatible `/v1/chat/completions`
endpoint using the strict system prompt in `app/llm/prompts.py`. The reply passes through
`app/llm/parser.py`, which tolerates prose wrapped around the JSON payload.

With `LLM_PROVIDER=mock` (the default for tests and CI), a deterministic scripted interpretation
is returned instead. Environment variables for the live provider are documented in `.env.example`.

---

## 8. Determinism & anti-cheat posture

This submission **never**:

- hard-codes scenario IDs, sample note wording, sample numbers, reference schedules, or expected outputs;
- regex-matches operator notes against a whitelist of public scenario phrasing;
- short-circuits the optimizer for any scenario;
- trusts an LLM-emitted number without routing it through `normalize_entries`.

The optimizer and post-validator are pure functions of the request body. Paraphrase the notes,
change the capacity, demand, tariff or solar profile, and the whole pipeline re-runs end to end
on the new input. The public-sample runner (`scripts/test_public_cases.py`) deliberately uses a
conservative phrase parser that extracts the *same directive semantics* the LLM would — by
construction, without ever looking at scenario IDs or expected outputs.

---

## 9. The LP formulation

For every hour `h ∈ [0, 23]`:

**Decision variables** (continuous, non-negative)

| Variable | Meaning | Bound |
| --- | --- | --- |
| `grid[h]` | kWh imported from the grid | ≥ 0 |
| `solar_used[h]` | kWh of solar consumed | ≤ `solar[h] * solar_factor[h]` |
| `charge[h]` | kWh into the battery | ≤ `max_charge_kwh_per_hour` |
| `discharge[h]` | kWh out of the battery | ≤ `max_discharge_kwh_per_hour` |
| `soc[h]` | state of charge at end of hour | `minimum_energy_kwh … capacity_kwh` |

**Objective**

```text
minimize  Σ grid[h] * tariff[h]
```

**Constraints**

```text
grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h]     # energy balance
soc[h]  == soc[h-1] + charge[h] - discharge[h]                      # SOC dynamics
soc[-1] == initial_energy_kwh                                       # initial condition
soc[23] == initial_energy_kwh                                       # end-of-day neutrality
charge[h] == 0   for h ∈ no_charge_hours                            # directive windows
```

No integrality is required, so CBC solves this as a pure continuous LP.

---

## 10. Testing

```bash
python -m pytest tests/ -q
```

33 tests, all running under `LLM_PROVIDER=mock`, so the suite is deterministic and offline.

| Test module | Coverage |
| --- | --- |
| `test_health.py` | `/health` payload shape |
| `test_schema.py` | `OptimizeRequest` validation — extra fields, missing hours, SOC above capacity |
| `test_directives.py` | Prose-only downgrades, unknown types, factor clamping, hour sanitization, reserve clamping, note-order alignment, garbage-in fallback |
| `test_optimizer.py` | Feasible plans under `no_op`, `no_charge_window`, `minimum_battery_reserve`; `build_hourly_plan` totals match raw solver values |
| `test_postvalidation.py` | Energy-balance violations, SOC floor breaches, end-of-day drift, solar cap, no-charge / no-discharge / max-grid window breaches |
| `test_api.py` | Full HTTP round-trips via `TestClient(create_app())` |

### Public-sample runner

```bash
python scripts/test_public_cases.py
```

Runs all 10 public scenarios through optimizer + post-validation using the generic phrase parser.
Prints `dirs=N/M` per case and a final `Feasible + post-validation OK: X/10` line.

---

## 11. Configuration reference

All settings live in `app/config.py` and are read from environment variables (or `.env`).

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | `mock` or `openai` |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `OPENAI_BASE_URL` | OpenAI public | Override for OpenAI-compatible providers |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for chat completions |
| `LLM_TIMEOUT_SECONDS` | `30` | HTTP timeout for the LLM call |
| `LLM_MAX_RETRIES` | `2` | Retries on transient LLM errors |
| `SOLVER_TIMEOUT_SECONDS` | `30` | Hard cap on CBC solve time |
| `SOLVER_MSG` | `0` | `0` = silent, `1` = verbose CBC output |
| `TOLERANCE_KWH` | `0.01` | Post-validation tolerance for kWh checks |
| `TOLERANCE_BDT` | `0.01` | Post-validation tolerance for BDT checks |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `HOST` | `0.0.0.0` | uvicorn bind host (used by Docker) |
| `PORT` | `8000` | uvicorn bind port (used by Docker) |

---

## 12. Repository layout

```text
app/
  main.py                          FastAPI factory + exception handler
  config.py                        Pydantic-settings (provider, timeouts, tolerances)
  exceptions.py                    GridWiseError hierarchy with status codes
  schemas.py                       Battery, HourRow, OptimizeRequest, ...
  api/routes.py                    /health + /optimize-energy
  services/
    optimizer_service.py           interpret -> validate -> solve -> post-validate
  llm/
    client.py                      Pluggable client (openai | mock)
    interpreter.py                 LLMInterpreter protocol + factory
    parser.py                      JSON extractor, robust to prose wrapping
    prompts.py                     System + user prompt templates
  optimization/
    model.py                       PuLP model: variables, objective, constraints
    solver.py                      solve() + build_hourly_plan()
    directive_helpers.py           DirectiveState per-hour accessors
    metrics.py                     Per-hour and total cost / peak calculations
  validation/
    directives.py                  normalize_entry / normalize_entries
    schedule.py                    validate_schedule (independent post-validation)

sample_cases/public_sample_cases.json    10 public scenarios
scripts/test_public_cases.p
