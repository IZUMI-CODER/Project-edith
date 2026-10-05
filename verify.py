"""Numeric verification of model answers with SymPy.

The model returns a machine-checkable `check` object next to its hints. We re-derive the
claim ourselves: differentiate the antiderivative, substitute the roots, count electrons.
Checks are numeric spot-checks (fast, no hanging simplify). Never raises.
Model output is untrusted: expressions are whitelisted before they reach the parser.
"""
import re

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor, implicit_multiplication_application, parse_expr, standard_transformations,
)

TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
FUNCS = {n: getattr(sp, n) for n in (
    "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "exp", "log", "sqrt", "Abs", "erf")}
FUNCS["ln"] = sp.log
CONSTS = {"pi": sp.pi, "E": sp.E, "oo": sp.oo}
PARSE_GLOBALS = {"__builtins__": {}, "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
                 "Symbol": sp.Symbol, "Function": sp.Function}
SAFE_CHARS = re.compile(r"^[0-9A-Za-z_+\-*/^().,\s]+$")
POINTS = [0.31, 0.77, 1.3, 2.1, -0.43, -1.2, 3.3]
SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
TOL = 1e-6


class Skip(Exception):
    pass


def _norm(s: str) -> str:
    s = s.replace("−", "-").replace("·", "*").replace("×", "*").replace("√", "sqrt")
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+", lambda m: "^(" + m.group().translate(SUPER) + ")", s)
    return re.sub(r"\bC\b", "0", s)  # integration constant


def parse(s: str, var: str = "x"):
    s = _norm(str(s))
    if not s.strip() or len(s) > 300 or not SAFE_CHARS.match(s) or "__" in s:
        raise Skip(f"cannot parse {s!r}")
    local = {**FUNCS, **CONSTS}
    for name in set(re.findall(r"[A-Za-z_]\w*", s)):
        if name in local:
            continue
        if len(name) == 1:
            local[name] = sp.Symbol(name)
        else:
            raise Skip(f"unknown name {name!r}")
    try:
        return parse_expr(s, local_dict=local, global_dict=dict(PARSE_GLOBALS), transformations=TRANSFORMS)
    except Exception as e:
        raise Skip(f"parse error: {e}")


def _val(expr, subs):
    v = complex(sp.N(expr.subs(subs), 30))
    if v != v or abs(v) == float("inf") or abs(v.imag) > 1e-9:
        raise ValueError("not real")
    return v.real


def _equal_at_points(f, g, var):
    ok = 0
    for p in POINTS:
        try:
            a, b = _val(f, {var: p}), _val(g, {var: p})
        except Exception:
            continue
        if abs(a - b) > TOL * (1 + abs(a)):
            return False, f"differ at {var}={p}: {a:.6g} vs {b:.6g}"
        ok += 1
    if ok < 3:
        raise Skip("too few valid test points")
    return True, f"matched at {ok} points"


def _integral(c):
    var = sp.Symbol(c.get("var") or "x")
    f, F = parse(c["expr"]), parse(c["result"])
    return _equal_at_points(sp.diff(F, var), f, var)


def _derivative(c):
    var = sp.Symbol(c.get("var") or "x")
    f, d = parse(c["expr"]), parse(c["result"])
    return _equal_at_points(sp.diff(f, var), d, var)


def _equation(c):
    var = sp.Symbol(c.get("var") or "x")
    lhs, _, rhs = str(c["expr"]).partition("=")
    expr = parse(lhs) - (parse(rhs) if rhs.strip() else 0)
    sols = [parse(s) for s in str(c["result"]).split(",") if s.strip()]
    if not sols:
        raise Skip("no solutions given")
    for s in sols:
        try:
            r = complex(sp.N(expr.subs(var, s), 30))
        except Exception:
            raise Skip("could not substitute")
        if abs(r) > TOL * (1 + abs(complex(sp.N(s, 30)))):
            return False, f"{var}={s} does not satisfy the equation (residual {abs(r):.3g})"
    note = f"{len(sols)} solution(s) satisfy the equation"
    try:
        poly = sp.Poly(expr, var)
        if 1 <= poly.degree() <= 8:
            real_roots = {round(float(sp.re(r)), 6) for r in poly.nroots() if abs(sp.im(r)) < 1e-9}
            given = {round(float(sp.N(s)), 6) for s in sols if abs(sp.im(sp.N(s))) < 1e-9}
            if real_roots - given:
                return False, f"missing real root(s): {sorted(real_roots - given)}"
            note += "; all real roots found"
    except Exception:
        pass
    return True, note


def _limit(c):
    var = sp.Symbol(c.get("var") or "x")
    f, target = parse(c["expr"]), parse(c["result"])
    if target.has(sp.oo):
        raise Skip("infinite limit not checked")
    point = parse(c.get("point", "0"))
    probes = [1e8, 1e10] if point.has(sp.oo) else [point + d for d in (1e-6, -1e-6, 1e-8, -1e-8)]
    t = float(sp.N(target))
    for p in probes:
        try:
            v = float(sp.N(f.subs(var, p), 50))
        except Exception:
            continue
        if abs(v - t) > 1e-4 * (1 + abs(t)):
            return False, f"f({p}) = {v:.6g}, expected near {t:.6g}"
    return True, "limit consistent numerically"


CORES = {"He": 2, "Ne": 10, "Ar": 18, "Kr": 36, "Xe": 54, "Rn": 86}
CAPACITY = {"s": 2, "p": 6, "d": 10, "f": 14}


def _electron_count(c):
    cfg = _norm(str(c["config"])).replace("^", "")
    total = 0
    for core in re.findall(r"\[(\w+)\]", cfg):
        if core not in CORES:
            raise Skip(f"unknown core {core}")
        total += CORES[core]
    for n, orb, k in re.findall(r"(\d)([spdf])(\d+)", re.sub(r"\[\w+\]", "", cfg)):
        if int(k) > CAPACITY[orb]:
            return False, f"{n}{orb}{k} exceeds the {CAPACITY[orb]}-electron limit (Pauli)"
        total += int(k)
    want = int(c["z"]) - int(c.get("charge") or 0)
    if total != want:
        return False, f"config holds {total} electrons, expected {want}"
    return True, f"{total} electrons and orbital capacities OK"


KINDS = {"integral": _integral, "derivative": _derivative, "equation": _equation,
         "limit": _limit, "electron_count": _electron_count}


def verify(check) -> dict:
    """Returns {"status": "pass"|"fail"|"skipped", "note": str}."""
    if not isinstance(check, dict) or check.get("kind") not in KINDS:
        return {"status": "skipped", "note": "not machine-checkable"}
    try:
        ok, note = KINDS[check["kind"]](check)
    except Skip as e:
        return {"status": "skipped", "note": str(e)}
    except Exception as e:  # malformed model output must never crash the request
        return {"status": "skipped", "note": f"check error: {type(e).__name__}"}
    return {"status": "pass" if ok else "fail", "note": note}
