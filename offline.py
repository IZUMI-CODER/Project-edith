"""Offline solver: no model, no API key, no cost. Rule-based + SymPy (+ optional OCR).

Honest scope: indefinite integrals, derivatives, single-variable equations, limits, and electron
configurations (incl. exceptions and ions). Anything else raises Unsupported so the UI can say so
instead of guessing. Hints are generated from the actual solution steps, so they are checkable.
"""
import concurrent.futures
import dataclasses
import re

import sympy as sp
from sympy.integrals.manualintegrate import integral_steps

import verify

MAX_HINT = 90
SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
UNSUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
SPECIAL_FUNCS = {"erf", "erfi", "erfc", "Ei", "Si", "Ci", "li", "fresnels", "fresnelc", "expint",
                 "uppergamma", "lowergamma", "polylog", "Chi", "Shi"}


KNOWN_FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "exp", "log", "sqrt", "abs", "for", "pi", "asin", "acos", "atan", "sinh", "cosh", "tanh"}


class Unsupported(Exception):
    pass


# ---------------------------------------------------------------- formatting / parsing
def fmt(e) -> str:
    s = str(e).replace("**", "^")
    s = s.replace("exp(", "e^(")
    s = re.sub(r"(?<=\d)\*(?=[A-Za-z(])", "", s)
    s = re.sub(r"\^(-?\d+)(?!\d)", lambda m: m.group(1).translate(SUP), s)
    s = re.sub(r"\bE\b", "e", s).replace("log(", "ln(")
    return s.replace("sqrt(", "√(").replace("*", "·").replace("pi", "π")


def clip(h: str) -> str:
    return h if len(h) <= MAX_HINT else h[:MAX_HINT - 1] + "…"


def to_sympy(s: str):
    s = s.replace("π", "pi")
    s = re.sub(r"√\s*(\w+|\([^()]*\))", r"sqrt(\1)", s)
    s = verify._norm(s)
    s = re.sub(r"\be\^(\((?:[^()]|\([^()]*\))*\)|[A-Za-z0-9.]+)", r"exp(\1)", s)
    s = re.sub(r"\be\b", "E", s)
    s = s.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    return verify.parse(s)


def strip_outer(s: str) -> str:
    s = s.strip()
    while len(s) > 1 and s[0] in "([{" and s[-1] in ")]}":
        depth = 0
        for i, ch in enumerate(s):
            depth += ch in "([{"
            depth -= ch in ")]}"
            if depth == 0 and i < len(s) - 1:
                return s
        s = s[1:-1].strip()
    return s


def pack(read_as, subject, concepts, hints, final, check, note=""):
    return {"read_as": read_as, "subject": subject, "ambiguity_note": note,
            "concepts": [{"name": n, "meaning": m} for n, m in concepts],
            "hints": [clip(h) for h in hints], "final_answer": final, "check": check}


# ---------------------------------------------------------------- chemistry
SYMBOLS = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
           "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb "
           "Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db "
           "Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og").split()
_NAMES = ("hydrogen helium lithium beryllium boron carbon nitrogen oxygen fluorine neon sodium magnesium aluminium "
          "silicon phosphorus sulfur chlorine argon potassium calcium scandium titanium vanadium chromium manganese "
          "iron cobalt nickel copper zinc gallium germanium arsenic selenium bromine krypton rubidium strontium "
          "yttrium zirconium niobium molybdenum technetium ruthenium rhodium palladium silver cadmium indium tin "
          "antimony tellurium iodine xenon").split()
NAMES = {n: i + 1 for i, n in enumerate(_NAMES)}
NAMES.update({"aluminum": 13, "sulphur": 16, "caesium": 55, "cesium": 55, "barium": 56, "platinum": 78,
              "tungsten": 74, "gold": 79, "mercury": 80, "lead": 82, "radon": 86, "uranium": 92})
assert len(SYMBOLS) == 118 and len(_NAMES) == 54

ORDER = [(1, "s"), (2, "s"), (2, "p"), (3, "s"), (3, "p"), (4, "s"), (3, "d"), (4, "p"), (5, "s"), (4, "d"),
         (5, "p"), (6, "s"), (4, "f"), (5, "d"), (6, "p"), (7, "s"), (5, "f"), (6, "d"), (7, "p")]
L = {"s": 0, "p": 1, "d": 2, "f": 3}
CAP = {k: 2 * (2 * v + 1) for k, v in L.items()}
CORES = [("Rn", 86), ("Xe", 54), ("Kr", 36), ("Ar", 18), ("Ne", 10), ("He", 2)]
# Ground-state exceptions to Madelung filling (subshell -> electrons), standard textbook values.
EXC = {
    "Cr": {"4s": 1, "3d": 5}, "Cu": {"4s": 1, "3d": 10}, "Nb": {"5s": 1, "4d": 4}, "Mo": {"5s": 1, "4d": 5},
    "Ru": {"5s": 1, "4d": 7}, "Rh": {"5s": 1, "4d": 8}, "Pd": {"5s": 0, "4d": 10}, "Ag": {"5s": 1, "4d": 10},
    "La": {"4f": 0, "5d": 1}, "Ce": {"4f": 1, "5d": 1}, "Gd": {"4f": 7, "5d": 1}, "Pt": {"6s": 1, "5d": 9},
    "Au": {"6s": 1, "5d": 10}, "Ac": {"5f": 0, "6d": 1}, "Th": {"5f": 0, "6d": 2}, "Pa": {"5f": 2, "6d": 1},
    "U": {"5f": 3, "6d": 1}, "Np": {"5f": 4, "6d": 1}, "Cm": {"5f": 7, "6d": 1},
}


def madelung(n_electrons: int) -> dict:
    occ, left = {}, n_electrons
    for n, o in ORDER:
        if left <= 0:
            break
        k = min(CAP[o], left)
        occ[f"{n}{o}"] = k
        left -= k
    return occ


def config_for(z: int, charge: int):
    sym = SYMBOLS[z - 1]
    if charge <= 0:
        occ = madelung(z - charge)
        if charge == 0 and sym in EXC:
            occ.update(EXC[sym])
    else:
        occ = madelung(z)
        if sym in EXC:
            occ.update(EXC[sym])
        for _ in range(charge):  # remove from highest n, then highest l
            sub = max((s for s, k in occ.items() if k > 0), key=lambda s: (int(s[0]), L[s[1]]))
            occ[sub] -= 1
    return {s: k for s, k in occ.items() if k > 0}


def ordered(occ: dict) -> list:
    names = [f"{n}{o}" for n, o in ORDER]
    return sorted(occ, key=names.index)


def core_split(occ: dict):
    for name, cz in CORES:
        need = madelung(cz)
        if all(occ.get(s) == k for s, k in need.items()):
            return name, cz, {s: k for s, k in occ.items() if s not in need}
    return None, 0, dict(occ)


def config_text(occ: dict, ascii_only=False) -> str:
    core, _, rest = core_split(occ)
    parts = ([f"[{core}]"] if core else []) + [
        f"{s}{k}" if ascii_only else f"{s}{str(k).translate(SUP)}" for s, k in ((s, rest[s]) for s in ordered(rest))]
    return " ".join(parts)


def unpaired(occ: dict) -> int:
    total = 0
    for s, k in occ.items():
        orb = 2 * L[s[1]] + 1
        total += k if k <= orb else 2 * orb - k
    return total


def find_element(text: str):
    t = text.translate(UNSUP).replace("−", "-")
    z = None
    m = re.search(r"\bZ\s*=\s*(\d+)|atomic number\s*(?:of\s*)?(\d+)", t, re.I)
    if m:
        z = int(m.group(1) or m.group(2))
    charge, sym = 0, None
    cand = []
    for m in re.finditer(r"\b([A-Z][a-z]?)(?:\s*\^?\s*\(?(\d*)([+-])\)?)?(?![A-Za-z])", t):
        if m.group(1) in SYMBOLS:
            cand.append(m)
    cand = [m for m in cand if m.group(1) not in ("A", "I")] or cand
    if cand:
        pick = next((m for m in cand if m.group(3)), cand[0])
        sym = pick.group(1)
        if pick.group(3):
            q = int(pick.group(2) or 1)
            charge = q if pick.group(3) == "+" else -q
    for w in re.findall(r"[a-z]+", t.lower()):
        if w in NAMES:
            z = z or NAMES[w]
            break
    if z is None and sym:
        z = SYMBOLS.index(sym) + 1
    if z is None or not 1 <= z <= 118:
        raise Unsupported("couldn't tell which element or atomic number")
    return z, charge


def solve_config(text: str) -> dict:
    z, charge = find_element(text)
    sym = SYMBOLS[z - 1]
    n_el = z - charge
    if n_el < 1:
        raise Unsupported("that ion would have no electrons")
    occ = config_for(z, charge)
    core, cz, rest = core_split(occ)
    label = sym + (f"{abs(charge) if abs(charge) > 1 else ''}{'+' if charge > 0 else '-'}" if charge else "")
    names = [f"{n}{o}" for n, o in ORDER]
    upto = names[:max(names.index(s) for s in madelung(n_el)) + 1]
    exc = charge == 0 and sym in EXC
    last = ordered(occ)[-1]
    partial = [s for s in occ if s[1] in "pdf" and occ[s] < CAP[s[1]]]
    h = [f"{sym} has Z = {z}: a neutral atom has {z} electrons." if not charge else
         f"{sym} has Z = {z}; with charge {charge:+d} it has {n_el} electrons.",
         "Aufbau: fill lowest energy first: " + " ".join(upto),
         "Pauli: max 2 e⁻ per orbital, so s holds 2, p 6, d 10, f 14.",
         f"Shortcut: start from the noble-gas core [{core}] ({cz} e⁻)." if core else "No core shortcut here: write every subshell from 1s."]
    if charge > 0:
        h.append("Cation: write the neutral atom, then remove e⁻ from the highest n first (4s before 3d).")
    elif charge < 0:
        h.append("Anion: add the extra e⁻ into the next open orbitals (Aufbau order).")
    if exc:
        h.append(f"Careful: {sym} is a known exception: half-filled or full d/f subshells are extra stable.")
    if charge <= 0:
        h.append(f"Place the remaining {n_el - cz} e⁻ into: " + ", ".join(ordered(rest)) + ("  (mind the exception)" if exc else ""))
    if partial:
        h.append(f"Hund: put one e⁻ in each {partial[-1]} box before pairing. How many stay unpaired?")
    h.append(f"Check: do all the superscripts add up to {n_el}?")
    concepts = [("Aufbau", "Fill the lowest-energy orbitals first."), ("Pauli exclusion", "Max 2 electrons per orbital, opposite spins.")]
    if partial:
        concepts.append(("Hund's rule", "Fill degenerate orbitals singly before pairing."))
    if exc:
        concepts.append(("Exception", "Half/full d or f subshells are extra stable."))
    if charge > 0:
        concepts.append(("Cation rule", "Remove e⁻ from the highest n shell first."))
    final = f"{label}: {config_text(occ)}   (unpaired electrons: {unpaired(occ)})"
    check = {"kind": "electron_count", "z": z, "charge": charge, "config": config_text(occ, ascii_only=True)}
    return pack(f"Electron configuration of {label} (Z = {z})", "Chemistry", concepts, h, final, check)


# ---------------------------------------------------------------- calculus
def _unwrap(rule):
    """Find the most informative step in a manualintegrate rule tree."""
    name = type(rule).__name__
    if name in ("URule", "PartsRule", "TrigSubstitutionRule", "PartialFractionsRule"):
        return rule
    if name == "AlternativeRule":
        found = [r for r in (_unwrap(a) for a in rule.alternatives) if r is not None]
        urules = [r for r in found if type(r).__name__ == "URule"]
        if urules:  # the textbook substitution is the simplest u
            return min(urules, key=lambda r: sp.count_ops(r.u_func))
        return found[0] if found else None
    for attr in ("substep",):
        sub = getattr(rule, attr, None)
        if sub is not None:
            return _unwrap(sub)
    for sub in getattr(rule, "substeps", None) or []:
        r = _unwrap(sub)
        if r is not None:
            return r
    return None


def solve_integral(text: str) -> dict:
    t = text.strip()
    if re.search(r"∫\s*[_^]|from\s+-?\w+\s+to\s|definite", t, re.I):
        raise Unsupported("definite integrals aren't supported offline yet")
    m = (re.search(r"(?:∫|integral of|integrate)\s*(.*?)\s*d([a-z])\s*$", t, re.I | re.S)
         or re.search(r"^[JfS]?\s*(.*?)\s*d([a-z])\s*$", t, re.S))
    if not m:
        raise Unsupported("couldn't find the integrand and d-variable")
    var = sp.Symbol(m.group(2))
    f = to_sympy(strip_outer(m.group(1)))
    read = f"∫ {fmt(f)} d{var}"
    F = sp.integrate(f, var)
    special = F.has(sp.Integral) or bool({a.func.__name__ for a in F.atoms(sp.Function)} & SPECIAL_FUNCS)
    if special:
        hints = ["Try the usual methods first: substitution, parts, rewriting.",
                 "Warning: some integrands have NO elementary antiderivative.",
                 f"Check the problem: is a factor missing (like 2{var} in front of e^({var}²))?",
                 "If it is correct as written, the answer needs a special function (erf, Ei, Si...).",
                 "For definite bounds, use numeric methods or series instead."]
        final = f"No elementary antiderivative. In special functions: {fmt(F)} + C" if not F.has(sp.Integral) else "No closed form found."
        check = {"kind": "integral", "expr": str(f), "result": str(F)} if not F.has(sp.Integral) else {"kind": "none"}
        return pack(read, "Calculus", [("Non-elementary integral", "Some integrals can't be written with elementary functions.")],
                    hints, final, check, note="This integrand has no elementary antiderivative.")
    try:
        step = _unwrap(integral_steps(f, var))
    except Exception:
        step = None
    kind = type(step).__name__ if step is not None else ""
    if kind == "URule":
        u = step.u_func
        hints = ["Look for an inner function whose derivative also appears in the integrand.",
                 "That pattern calls for u-substitution.",
                 f"Let u = {fmt(u)}. What is du in terms of d{var}?",
                 "Rewrite the whole integral using only u and du.",
                 f"Integrate with respect to u, then replace u by {fmt(u)}.",
                 "Check: differentiate your result. Do you get the original integrand?"]
        concepts = [("u-substitution", "Reverse chain rule: swap an inner function for u."),
                    ("Chain rule", "d/dx f(g(x)) = f'(g(x))·g'(x)")]
    elif kind == "PartsRule":
        hints = ["A product of different function types: try integration by parts.",
                 "Parts formula: ∫u dv = uv − ∫v du.",
                 f"Choose u = {fmt(step.u)} and dv = {fmt(step.dv)} d{var}. Find du and v.",
                 "Plug into the formula. Is the new integral easier than the old one?",
                 "Finish the remaining integral (repeat parts if needed), then simplify.",
                 "Check: differentiate your result. Do you get the original integrand?"]
        concepts = [("Integration by parts", "∫u dv = uv − ∫v du"), ("LIATE", "Pick u: Log, Inverse trig, Algebraic, Trig, Exp.")]
    elif kind in ("TrigSubstitutionRule", "PartialFractionsRule"):
        what = "trig substitution" if kind.startswith("Trig") else "partial fractions"
        hints = [f"This form calls for {what}.", "Set it up, then change the integral to the new variable.",
                 "Integrate the simpler pieces.", "Convert back to the original variable.",
                 "Check: differentiate your result. Do you get the original integrand?"]
        concepts = [(what.capitalize(), "Standard technique for this integrand shape.")]
    else:
        hints = ["Split into terms and spot standard forms (power, e^x, trig, 1/x).",
                 "Apply the matching basic rule to each term.",
                 "Power rule: ∫x^n dx = x^(n+1)/(n+1), for n ≠ −1.",
                 "Add + C once at the end and simplify.",
                 "Check: differentiate your result. Do you get the original integrand?"]
        concepts = [("Basic integration rules", "Power, exponential and trig antiderivatives.")]
    return pack(read, "Calculus", concepts, hints, f"{fmt(F)} + C", {"kind": "integral", "expr": str(f), "result": str(F), "var": str(var)})


def _classify(f, v):
    if f.is_Add:
        dep = [a for a in f.args if a.has(v)]
        return ("sum", None) if len(dep) > 1 else _classify(dep[0], v) if dep else ("const", None)
    if f.is_Mul:
        dep = [a for a in f.args if a.has(v)]
        if len(dep) >= 2:
            return ("quotient", None) if any(a.is_Pow and a.exp.is_negative for a in dep) else ("product", None)
        return _classify(dep[0], v) if dep else ("const", None)
    if f.is_Pow:
        if f.exp.has(v):
            return ("expo", None) if not f.base.has(v) else ("logdiff", None)
        return ("power", None) if f.base == v else ("chain", (f"power {fmt(f.exp)}", f.base))
    if f.is_Function and f.args:
        return ("standard", None) if f.args[0] == v else ("chain", (f.func.__name__, f.args[0]))
    return ("standard", None)


def solve_derivative(text: str) -> dict:
    t = text.strip()
    m = (re.search(r"d\s*/\s*d([a-z])\s*(.+)$", t, re.S)
         or re.search(r"(?:derivative of|differentiate)\s+(.+?)(?:\s+with respect to\s+([a-z]))?\s*$", t, re.I | re.S))
    if not m:
        raise Unsupported("couldn't find what to differentiate")
    if m.re.pattern.startswith("d\\s*/"):
        var, body = sp.Symbol(m.group(1)), m.group(2)
    else:
        body = m.group(1)
        var = sp.Symbol(m.group(2) or "x")
    body = re.sub(r"^\s*[a-z]\s*\(\s*[a-z]\s*\)\s*=", "", body)
    f = to_sympy(strip_outer(body))
    kind, extra = _classify(f, var)
    ans = sp.diff(f, var)
    steps = {
        "sum": (["It's a sum: differentiate term by term.", "Handle each term with its own rule.", "Add the results."],
                [("Sum rule", "(f+g)' = f' + g'")]),
        "product": (["Two x-dependent factors multiplied: use the product rule.", "Product rule: (fg)' = f'g + fg'.",
                     "Differentiate each factor separately.", "Combine, then simplify."],
                    [("Product rule", "(fg)' = f'g + fg'")]),
        "quotient": (["A ratio of x-dependent parts: use the quotient rule.", "Quotient rule: (f/g)' = (f'g − fg')/g².",
                      "Differentiate numerator and denominator separately.", "Combine over g², then simplify."],
                     [("Quotient rule", "(f/g)' = (f'g − fg')/g²")]),
        "chain": (["Spot the outer function and the inner function.",
                   f"Outer: {extra[0] if extra else ''}. Inner: {fmt(extra[1]) if extra else ''}.",
                   "Chain rule: d/dx f(g) = f'(g)·g'.", "Differentiate the outer function, keeping the inner as is.",
                   "Multiply by the derivative of the inner function."], [("Chain rule", "d/dx f(g(x)) = f'(g(x))·g'(x)")]),
        "power": (["Power rule: d/dx x^n = n·x^(n−1).", "Bring the exponent down, reduce it by one."], [("Power rule", "d/dx x^n = n x^(n−1)")]),
        "expo": (["Constant base with x in the exponent: a^x differentiates to a^x·ln(a).", "Don't forget any chain-rule factor."],
                 [("Exponential rule", "d/dx a^x = a^x ln a")]),
        "logdiff": (["Variable base AND exponent: use logarithmic differentiation.", "Take ln of both sides, differentiate implicitly.",
                     "Solve for the derivative and substitute back."], [("Logarithmic differentiation", "y = f^g → ln y = g ln f")]),
        "standard": (["Recall the standard derivative of this function.", "Apply it directly."], [("Standard derivatives", "Memorise the basic table.")]),
        "const": (["Nothing depends on the variable: the derivative is 0."], [("Constant rule", "d/dx c = 0")]),
    }
    hints, concepts = steps[kind]
    hints = hints + ["Check: pick a number, compare the slope numerically with your formula."]
    return pack(f"d/d{var} [ {fmt(f)} ]", "Calculus", concepts, hints, fmt(ans),
                {"kind": "derivative", "expr": str(f), "result": str(ans), "var": str(var)})


def solve_limit(text: str) -> dict:
    m = re.search(r"lim(?:it)?\s*[_{(]*\s*([a-z])\s*(?:→|->|to)\s*([-+]?[\w.]+|∞)\s*[)}]*\s*(?:of)?\s*(.+)$", text.strip(), re.I | re.S)
    if not m:
        raise Unsupported("couldn't parse the limit")
    var = sp.Symbol(m.group(1))
    pt = sp.oo if m.group(2) in ("∞", "oo", "inf", "infinity") else to_sympy(m.group(2))
    f = to_sympy(strip_outer(m.group(3)))
    try:
        direct = f.subs(var, pt)
    except Exception:
        direct = sp.nan
    L = sp.limit(f, var, pt)
    indeterminate = direct in (sp.nan, sp.zoo) or direct.has(sp.nan) or (pt == sp.oo and direct.has(sp.oo))
    hints = ["Substitute the limit value first. What form do you get?"]
    if indeterminate:
        hints.append("An indeterminate form (0/0, ∞/∞): you can't stop at substitution.")
        if f.has(sp.sin) or f.has(sp.cos):
            hints.append("Recall the standard limit sin(u)/u → 1 as u → 0.")
        hints += ["Simplify: factor, cancel or rationalize. Or apply L'Hôpital's rule.", "Re-evaluate at the limit point."]
    else:
        hints += ["A finite, defined value means substitution already gives the limit."]
    hints.append("Check that approaching from both sides gives the same value.")
    final = f"lim = {fmt(L)}"
    check = {"kind": "limit", "expr": str(f), "point": str(pt), "result": str(L), "var": str(var)} if L.is_number and L.is_finite else {"kind": "none"}
    return pack(f"lim {var}→{fmt(pt)} of {fmt(f)}", "Calculus", [("Limits", "Value the function approaches near a point."),
                ("L'Hôpital's rule", "0/0 or ∞/∞: differentiate top and bottom.")], hints, final, check)


def solve_equation(text: str) -> dict:
    body = re.sub(r"^\s*(?:please\s+)?(?:solve|find x|find the roots of)\s*(?:for\s+[a-z]\s*)?:?", "", text.strip(), flags=re.I)
    body = re.sub(r"\s+for\s+[a-z]\s*$", "", body, flags=re.I)
    if "=" not in body:
        raise Unsupported("no equation found")
    lhs, rhs = (to_sympy(strip_outer(p)) for p in body.split("=", 1))
    expr = lhs - rhs
    syms = sorted(expr.free_symbols, key=str)
    if len(syms) != 1:
        raise Unsupported("only single-variable equations are supported")
    v = syms[0]
    sols = sp.solveset(sp.Eq(lhs, rhs), v, domain=sp.S.Reals)
    try:
        deg = sp.Poly(expr, v).degree()
    except sp.PolynomialError:
        deg = None
    if deg == 2:
        hints = [f"Move everything to one side: a{v}² + b{v} + c = 0.", "Identify a, b and c.",
                 "Try factoring first. If that fails, use the discriminant b² − 4ac.",
                 "Sign of b² − 4ac: positive = 2 real roots, zero = 1, negative = none.",
                 f"Apply the quadratic formula (or set each factor to 0) to get {v}.", "Check each root by substituting it back."]
        concepts = [("Quadratic formula", "x = (−b ± √(b²−4ac)) / 2a"), ("Discriminant", "b²−4ac tells how many real roots.")]
    elif deg == 1:
        hints = [f"Goal: get {v} alone.", "Do the same operation to both sides.", "Undo addition/subtraction first, then multiplication/division.",
                 "Check by substituting your answer back."]
        concepts = [("Inverse operations", "Undo operations in reverse order.")]
    else:
        hints = ["Try to bring everything to one side and factor.", "Look for a substitution that simplifies the shape.",
                 "Solve each factor separately.", "Check every candidate: some may be extraneous."]
        concepts = [("Factoring", "Zero-product property: ab = 0 → a = 0 or b = 0.")]
    if sols.is_FiniteSet and len(sols) > 0:
        roots = sorted(sols, key=lambda r: float(sp.N(r)))
        final = " or ".join(f"{v} = {fmt(r)}" for r in roots)
        check = {"kind": "equation", "expr": f"{lhs} = {rhs}", "result": ", ".join(str(r) for r in roots), "var": str(v)}
    elif sols is sp.S.EmptySet:
        final, check = "No real solutions.", {"kind": "none"}
    else:
        raise Unsupported("couldn't solve that equation in closed form")
    return pack(f"Solve {fmt(lhs)} = {fmt(rhs)}", "Algebra", concepts, hints, final, check)


# ---------------------------------------------------------------- dispatch
def solve(text: str) -> dict:
    t = text.strip()
    lo = t.lower()
    if re.search(r"electron(?:ic)?\s+config|e-?\s*config|configuration of", lo):
        return solve_config(t)
    if re.search(r"\blim\b|\blimit\b", lo):
        return solve_limit(t)
    if "∫" in t or re.search(r"\bintegra", lo) or (re.search(r"\bd[xyt]\s*$", t) and "=" not in t and not re.search(r"d\s*/\s*d", t)):
        return solve_integral(t)
    if re.search(r"d\s*/\s*d[a-z]|derivative|differentiate", lo):
        return solve_derivative(t)
    if "=" in t:
        body = re.sub(r"^\s*(?:please\s+)?solve\b", "", t, flags=re.I)
        words = [w for w in re.findall(r"[A-Za-z]{3,}", body) if w.lower() not in KNOWN_FUNCS]
        if words:
            raise Unsupported("word problems need a model backend (docs/FREE.md)")
        return solve_equation(t)
    raise Unsupported("this type of problem isn't covered offline yet (try a model backend, see docs/FREE.md)")


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def solve_safely(text: str, timeout: float = 12.0) -> dict:
    fut = _pool.submit(solve, text)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise Unsupported("that took too long to solve offline")
    except verify.Skip as e:
        raise Unsupported(f"couldn't parse the expression ({e})")
    except (sp.SympifyError, sp.PolynomialError, ValueError, TypeError, ZeroDivisionError, NotImplementedError, RecursionError) as e:
        raise Unsupported(f"couldn't solve it ({type(e).__name__})")


# ---------------------------------------------------------------- OCR (optional)
_ocr = None


def repair_ocr(text: str) -> str:
    """Fix the confusions OCR makes on maths. The UI still shows the result for the user to confirm."""
    t = text.strip().replace("~", "^")
    t = re.sub(r"(?<![A-Za-z])([xyzt])(\d+)(?![\d.])", r"\1^\2", t)      # x3 -> x^3 (lost superscript)
    if re.search(r"(?:\s|\))d[xyt]\s*$", t):
        t = re.sub(r"^[{|JfSʃ]\s*", "∫ ", t)                               # lost integral sign
    return t


def ocr(image_bytes: bytes) -> str:
    """Printed-text OCR via rapidocr-onnxruntime (models ship inside the wheel). Handwriting is weak."""
    global _ocr
    from rapidocr_onnxruntime import RapidOCR  # ImportError -> caller explains how to install
    _ocr = _ocr or RapidOCR()
    result, _ = _ocr(image_bytes)
    return repair_ocr(" ".join(r[1] for r in (result or [])))
