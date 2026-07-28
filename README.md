# SpecGuard

**Generate from spec, guard against drift.**

SpecGuard is an AI-assisted API testing tool with two halves:

1. **Generate** — point it at an OpenAPI 3.x spec and get a *review-ready*
   pytest suite: happy path, validation failures, boundary values, and auth
   boundaries. You review and commit it — nothing is auto-committed.
2. **Guard** — record a baseline of your API's real response shapes, then catch
   **contract drift** on every run: a renamed field, a changed type, a new enum
   value — before it reaches your consumers.

> One line: *generate the tests from your spec, then keep them honest as the API changes.*

> ⚠️ **Status: early development / design phase.** The design is complete and
> the build is in progress. Interfaces may change. Not yet on PyPI.

---

## Why

Writing API tests by hand is slow and uneven — people cover the happy path and
skip the negative, boundary, and auth cases under deadline pressure. And once
tests exist, the API drifts: a field goes nullable, a type changes, an enum
gains a value. The tests still pass because they only assert what someone
happened to think of, so **silent contract drift** reaches consumers before
anyone notices.

SpecGuard attacks both problems with one tool, and keeps the AI in a narrow,
reviewable role — a deterministic core does everything that gates or asserts.

---

## How it works

```
GENERATE   openapi.yaml → parse → design cases → render pytest → [review] → commit
GUARD      live API → baseline (record contract) → guard (diff & report drift)
```

- **Deterministic core.** The spec parser, schema inference, diff engine, and
  test renderer are all reproducible and testable with no model involved.
- **AI at the edges only.** An LLM proposes *extra* test cases it infers from
  natural-language field descriptions, and optionally explains a drift finding
  in prose. It never decides pass/fail on its own.
- **Pluggable model.** Use a hosted model (Claude API) or a fully local one
  (Ollama) behind a single interface. Local keeps your data in your environment.

---

## Planned CLI

```bash
# generate a reviewable test suite from a spec
specguard generate openapi.yaml --out generated/ --provider claude

# record current responses as the contract baseline
specguard baseline --base-url https://api.staging.example.com --out baseline.json

# compare live responses to the baseline; fail CI on breaking drift
specguard guard --base-url https://api.staging.example.com \
                --baseline baseline.json --report drift.json \
                --fail-on breaking

# run the generated suite and emit JUnit
specguard run generated/ --junitxml results.xml
```

Drift is classified deterministically: a removed or renamed required field or a
type change is **breaking**; a new enum value is a **warning**; a new optional
field is **info**. You choose what gates your build with `--fail-on`.

---

## Roadmap

- [ ] **M1** — OpenAPI parsing → endpoint model (no LLM)
- [ ] **M2** — Generate half: spec → runnable pytest suite (deterministic floor + LLM extras)
- [ ] **M3** — Guard half: baseline + drift detection with fixed severities
- [ ] **M4** — CLI, CI integration, JUnit output, published to PyPI

---

## Design

The full design document (architecture, module interfaces, data models, prompts)
lives in [`docs/`](docs/). SpecGuard follows one principle throughout: **the AI
is narrow and reviewable, never silent authority over pass/fail.**

---

## Stack

Python · pytest · jsonschema · Jinja2 · OpenAPI · Claude API or Ollama.

---

## License

MIT (planned).

---

*Built by [Atharva Rane](https://github.com/athrvrne) — author of
[pytest-self-healer](https://pypi.org/project/pytest-self-healer).*
