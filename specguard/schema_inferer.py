"""Real responses -> inferred JSON Schema + value statistics.

This is the core of the Guard half and it is deliberately free of any model:
the thing that decides whether your API drifted has to be reproducible.

Inference is *conservative by design*. A schema that is too strict produces
false drift on every run, which trains people to ignore the tool — a worse
outcome than missing a change.
"""

# A string field only becomes an enum when the evidence genuinely supports a
# closed set. Free-text fields would otherwise drift on every new sentence.
ENUM_MAX_DISTINCT = 10
ENUM_MAX_DISTINCT_RATIO = 0.2
ENUM_MIN_SAMPLE = 20

# Below this, "present in every response" is weak evidence of "required".
LOW_CONFIDENCE_SAMPLE = 20


def infer(responses: list) -> dict:
    """Infer a contract from observed responses.

    Returns the schema, per-field statistics keyed by dotted path, the number
    of observations it rests on, and whether that number is thin enough that a
    human should treat the result with suspicion.
    """
    observations = _observations(responses)
    if not observations:
        return {
            "inferred_schema": {},
            "value_stats": {},
            "sample_size": 0,
            "low_confidence": True,
        }

    stats: dict[str, dict] = {}
    schema = _infer_node(responses, stats, path="")
    return {
        "inferred_schema": schema,
        "value_stats": stats,
        "sample_size": len(observations),
        "low_confidence": len(observations) < LOW_CONFIDENCE_SAMPLE,
    }


def infer_schema(responses: list) -> dict:
    """Just the schema, for callers that don't need the statistics."""
    return infer(responses)["inferred_schema"]


def _observations(responses: list) -> list:
    """The values the schema actually rests on.

    A single call returning 30 list items is 30 observations of the item shape,
    not one — which is what makes collection endpoints cheap to baseline.
    """
    if responses and all(isinstance(r, list) for r in responses):
        return [item for response in responses for item in response]
    return list(responses)


# --- inference --------------------------------------------------------------


def _infer_node(values: list, stats: dict, path: str) -> dict:
    """Infer the schema for one position, given every value observed there."""
    present = [v for v in values if v is not None]
    nullable = len(present) < len(values)

    if present and all(isinstance(v, dict) for v in present):
        return _infer_object(present, stats, path)
    if present and all(isinstance(v, list) for v in present):
        return _infer_array(present, stats, path)

    node = _infer_scalar(present, path, stats)
    if path:
        stats.setdefault(path, {})["nullable"] = nullable
    return node


def _infer_object(values: list[dict], stats: dict, path: str) -> dict:
    keys_in_all = set(values[0])
    seen: dict[str, list] = {}
    for value in values:
        keys_in_all &= set(value)
        for key, item in value.items():
            seen.setdefault(key, []).append(item)

    return {
        "type": "object",
        "required": sorted(keys_in_all),
        "properties": {
            key: _infer_node(observed, stats, _join(path, key))
            for key, observed in sorted(seen.items())
        },
    }


def _infer_array(values: list[list], stats: dict, path: str) -> dict:
    pooled = [item for value in values for item in value]
    node = {"type": "array"}
    if pooled:
        node["items"] = _infer_node(pooled, stats, _join(path, "[]"))
    return node


def _infer_scalar(values: list, path: str, stats: dict) -> dict:
    types = sorted({_json_type(v) for v in values})
    node: dict = {"type": types[0] if len(types) == 1 else types}

    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if numbers and path:
        entry = stats.setdefault(path, {})
        entry["min"] = min(numbers)
        entry["max"] = max(numbers)

    strings = [v for v in values if isinstance(v, str)]
    if types == ["string"] and _looks_like_enum(strings):
        observed = sorted(set(strings))
        node["enum"] = observed
        if path:
            stats.setdefault(path, {})["observed_values"] = observed

    return node


def _looks_like_enum(values: list[str]) -> bool:
    """Only when the observed set is small and stable relative to the sample."""
    if len(values) < ENUM_MIN_SAMPLE:
        return False
    distinct = len(set(values))
    if distinct > ENUM_MAX_DISTINCT:
        return False
    return distinct / len(values) <= ENUM_MAX_DISTINCT_RATIO


def _json_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def _join(path: str, key: str) -> str:
    if not path:
        return key
    return f"{path}.{key}" if key != "[]" else f"{path}[]"
