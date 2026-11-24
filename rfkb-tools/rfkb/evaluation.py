from .validation import KBError, UNITS, decimal_text, interval, number


def measurement(value, quantity, *, tolerance_required=False):
    if not isinstance(value, dict):
        raise KBError("Missing structured parameter.")
    unit = value.get("unit")
    if not isinstance(unit, str) or unit not in UNITS or UNITS[unit][0] != quantity:
        raise KBError("Parameter unit does not match the required quantity.")
    if tolerance_required and ("lower" not in value or "upper" not in value):
        raise KBError("Explicit manufacturing tolerance bounds are required.")
    if "value" in value:
        if "lower" in value or "upper" in value:
            raise KBError("Supply either a scalar or an interval, not both.")
        lo = hi = number(value["value"])
    else:
        if value.get("lower") is None or value.get("upper") is None:
            raise KBError("Both manufacturing tolerance bounds are required.")
        lo, hi = number(value["lower"]), number(value["upper"])
        if lo > hi:
            raise KBError("Parameter tolerance bounds are reversed.")
    factor = UNITS[unit][1]
    return lo * factor, hi * factor


def bounded_check(identifier, quantity, unit, lower, upper, measured):
    factor = UNITS[unit][1]
    lo = None if lower is None else number(lower) * factor
    hi = None if upper is None else number(upper) * factor
    ml, mh = measured
    outcome = "fail" if ((lo is not None and ml < lo) or (hi is not None and mh > hi)) else "pass"
    return {
        "id": identifier, "outcome": outcome, "quantity": quantity,
        "normalized_unit": {"length": "mm", "angle": "deg", "dimensionless": "1"}[quantity],
        "measured": {"lower": decimal_text(ml), "upper": decimal_text(mh)},
        "limits": {"lower": None if lo is None else decimal_text(lo),
                   "upper": None if hi is None else decimal_text(hi)},
    }


def check_parameters(profile, parameters, rules):
    checks = []
    known = {d["id"] for d in profile["body"]["constraints"]}
    if set(parameters) - known:
        checks.append({"id": "unknown_inputs", "outcome": "insufficient_data",
                       "reason": "Unknown semantic input IDs: " + ", ".join(sorted(set(parameters) - known))})
    for spec in profile["body"]["constraints"]:
        try:
            measured = measurement(parameters.get(spec["id"]), spec["quantity"])
            result = bounded_check(spec["id"], spec["quantity"], spec["unit"],
                                   spec.get("lower"), spec.get("upper"), measured)
        except KBError as exc:
            result = {"id": spec["id"], "outcome": "insufficient_data", "reason": str(exc)}
        checks.append(result)
    for rule in rules:
        spec = rule["body"]
        try:
            hole = measurement(parameters.get(spec["hole"]), "length", tolerance_required=True)
            shaft = measurement(parameters.get(spec["shaft"]), "length", tolerance_required=True)
            measured = (hole[0] - shaft[1], hole[1] - shaft[0])
            result = bounded_check(rule["record_id"], "length", spec["unit"],
                                   spec.get("lower"), spec.get("upper"), measured)
        except (KBError, KeyError) as exc:
            result = {"id": rule["record_id"], "outcome": "insufficient_data", "reason": str(exc)}
        result["rule_version"] = rule["version"]
        checks.append(result)
    outcomes = {c["outcome"] for c in checks}
    outcome = ("fail" if "fail" in outcomes else
               "insufficient_data" if "insufficient_data" in outcomes or not checks else "pass")
    return {"outcome": outcome, "checks": checks,
            "test_only": profile["test_only"],
            "limitations": "These checks do not certify RF, mechanical, manufacturing or standards compliance. "
                           + ("Synthetic test data; not for engineering use." if profile["test_only"] else
                              "Only the specified, versioned interval and clearance checks were executed.")}
