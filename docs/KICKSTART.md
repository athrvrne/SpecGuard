# SpecGuard — Kickstart Brief (private, keep out of the public README)

> This is the "restart cold" doc. If you've been away for months, read this
> top to bottom and you'll have everything you need to start coding again.
> Working name: **SpecGuard**. Rename freely.

---

## What it is, in one paragraph

An AI-assisted API testing tool with two halves that share one story:
**generate from spec, guard against drift.**

- **Generate:** point it at an OpenAPI 3.x spec → it produces a *review-ready*
  pytest suite (happy path, validation failures, boundary values, auth
  boundaries), which a human reviews and commits.
- **Guard:** record a per-endpoint baseline of real response shapes, then on
  every later run diff live responses against it and report contract/behavior
  drift (removed/renamed/type-changed fields, new enum values, value anomalies).

One line: *generate the tests from the spec, then keep them honest as the API drifts.*

---

## The non-negotiable design principle (this is the whole philosophy)

**The AI is narrow and reviewable, never silent authority over pass/fail.**
- Deterministic core: spec parser, schema inference, diff engine, renderer,
  runner, reporter — all reproducible and unit-testable with NO model.
- LLM is confined to exactly two bounded jobs:
  1. proposing *extra* test cases inferred from natural-language field
     descriptions the schema can't encode ("must be a future date").
  2. writing an *optional* human-readable explanation of a drift finding.
- Generated tests land in a `generated/` dir flagged for review — never
  auto-committed. Drift findings are surfaced; a human promotes them to gates.
- If the LLM is unavailable, the deterministic floor still generates a solid
  suite and Guard still works fully. The model is an authoring aid, not a
  runtime dependency.

This is the same judgment that's in pytest-self-healer (repairs locators, not
assertions; surfaces for review). Reuse it — it's what makes the tool credible.

---

## Architecture (two pipelines over shared infra)

```
GENERATE:  openapi.yaml
  -> spec_parser     -> List[EndpointModel]        (deterministic)
  -> case_designer   -> List[TestCase]             (deterministic matrix + LLM extras)
  -> test_renderer   -> pytest .py (Jinja2)        (deterministic)
  -> [HUMAN REVIEW]  -> committed suite

GUARD:     live API + suite
  -> runner          -> captured responses         (deterministic)
  -> schema_inferer  -> inferred schema + stats     (baseline mode)
  -> drift_engine    -> diff(baseline, current)     (guard mode, fixed severities)
  -> reporter        -> drift_report.json / console / JUnit (+ optional LLM summary)
  -> [HUMAN CONFIRM] -> promote finding to a gating assertion
```

Two Guard modes:
- **baseline mode** (`specguard baseline`): record current responses as the
  contract source of truth. Explicit, human-triggered — never silently overwrite.
- **guard mode** (`specguard guard`): compare live responses to baseline, report drift.

---

## Modules (build order matters — see milestones)

| Module | Job | Deterministic? |
|---|---|---|
| `spec_parser` | OpenAPI 3.x → EndpointModel | Yes |
| `models` | EndpointModel, TestCase, Finding dataclasses | Yes |
| `llm/provider` | LLMProvider protocol | (interface) |
| `llm/claude` | Claude impl (anthropic SDK, key from env) | No, isolated |
| `llm/ollama` | local impl (POST localhost:11434) | No, isolated |
| `case_designer` | EndpointModel → TestCase list (matrix + LLM extras) | Core yes |
| `test_renderer` | TestCase list → pytest source (Jinja2) | Yes |
| `runner` | execute requests, capture responses | Yes |
| `schema_inferer` | responses → inferred schema + value_stats | Yes |
| `drift_engine` | diff(baseline, current) → findings w/ severities | Yes |
| `reporter` | findings → JSON / console / JUnit | Yes |
| `cli` | command surface (click or typer), wiring | Yes |

**Write the interfaces first:** `LLMProvider` protocol, `EndpointModel`,
`TestCase`, `Finding`. Everything hangs off those.

---

## Key data models

- **EndpointModel**: method, path, operation_id, path_params, query_params,
  request_schema, response_schema, success_status, requires_auth.
- **TestCase**: name, kind (happy|validation|boundary|auth|llm_extra), method,
  path, body, headers, expected_status, assertions[].
- **Finding**: endpoint, severity (breaking|warning|info), kind, field, detail.

Three persisted JSON artifacts (keep them plain JSON so they diff in Git):
- `baseline.json` — per-endpoint inferred_schema + value_stats + success_status.
- `drift_report.json` — findings[] + summary counts.
- generated pytest files under `generated/`.

**Severity rules are deterministic code, not AI:**
- removed/renamed required field, or type change → **breaking**
- new enum value, widened type → **warning**
- new optional field → **info**

---

## Schema inference logic (the core of Guard)

Given N real responses for an endpoint:
- field present in ALL responses → `required`
- field type = union of observed types
- string field with a small, stable value set → infer an `enum`
- record numeric min/max + nullability as `value_stats`
- only infer enum when the observed value set is small/stable vs sample size,
  else leave as plain string (avoids false drift on free-text fields)
- baseline from N>=20 responses; treat single-observation fields as optional.

---

## CLI surface

```
specguard generate openapi.yaml --out generated/ --provider claude
specguard baseline --base-url https://api.staging.example.com --out baseline.json
specguard guard    --base-url https://api.staging.example.com \
                   --baseline baseline.json --report drift_report.json \
                   --fail-on breaking
specguard run generated/ --junitxml results.xml
```

`--fail-on {breaking|warning|info}` is how the human keeps control of gating.
Guard is LLM-free; only `generate` needs a model.

---

## Build milestones (ship M1–M2 first, demo early)

- **M1 — spec parsing.** `parse_spec()` turns Petstore into EndpointModels,
  fully unit-tested. No LLM yet.
- **M2 — Generate half.** `specguard generate` emits a runnable pytest suite;
  deterministic matrix works with the LLM OFF.
- **M3 — Guard half.** `baseline` + `guard` detect a renamed field as breaking
  drift on a demo API.
- **M4 — CLI + CI + polish.** All four commands; JUnit output; README with the
  rename-a-field demo GIF; publish to PyPI.

**The demo that sells it:** point at an API, `baseline`, rename a required
field, `guard` → it reports a breaking drift at the exact field. Record this
as a 3-min GIF; it's the top of the README and the best sales asset.

---

## Repo layout (target)

```
specguard/
  specguard/
    __init__.py
    spec_parser.py      models.py
    llm/ (provider.py, claude.py, ollama.py)
    case_designer.py    test_renderer.py
    runner.py           schema_inferer.py
    drift_engine.py     reporter.py
    cli.py
  templates/test_module.py.j2
  tests/                # SpecGuard's OWN tests
  examples/petstore.yaml
  pyproject.toml  README.md
```

## Testing SpecGuard itself
- Unit-test deterministic modules against Petstore with golden outputs.
- Snapshot-test the renderer (same TestCase list → identical pytest).
- For the LLM module, test PARSING of model output (malformed JSON, extra
  prose) with recorded fixtures — don't call a live model in tests.
- E2E: tiny fake API + spec + deliberate field rename → exactly one breaking finding.

---

## Stack
Python · pytest · jsonschema · Jinja2 · click/typer · PyYAML ·
anthropic SDK (Claude) or Ollama (local) · requests.

---

## If/when it becomes a service (deferred — usage first)
- **Runner-local architecture:** the OSS CLI runs inside the customer's CI and
  touches their creds/data; only findings + inferred schema go to the backend.
  This is the trust model regulated buyers require. Don't compromise it.
- OSS CLI = distribution + free tier. Paid platform sells what the CLI can't:
  drift history, dashboards, Slack/PR alerts, team baselines, trends.
- Bill per monitored API + per seat. Never per test run. Self-hosted tier for
  regulated buyers is a real revenue line.
- Do NOT build the backend before the free CLI has real adoption. Ship the
  runner, watch weekly `guard`-in-CI usage, let that pull you into the service.
- Full GTM + first-client playbook exists as a separate doc (design partners,
  outreach scripts, the closing demo).

---

## The very first coding move when you come back
1. `pip install pytest jsonschema jinja2 click pyyaml anthropic`
2. Write `models.py` (EndpointModel, TestCase, Finding) + `llm/provider.py`.
3. Write `spec_parser.parse_spec()` against `examples/petstore.yaml`, unit-test it.
4. That's M1. Then the deterministic `_deterministic_matrix` in case_designer.
Everything else follows.

---

## Companion docs from the original design session
- **Design doc** (full architecture, module code, prompts, data models) — the
  authoritative spec; this brief is its condensed restart version.
- **Go-to-market plan** (business model, ICP, pricing, 90-day launch, outreach
  scripts, closing demo, pitfalls).
Keep both alongside this brief.
