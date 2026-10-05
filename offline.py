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
    s = re.sub(r"(?<=[0-9a-z)])e\^", "*e^", s)                              # OCR drops spaces: 2xe^(x²) -> 2x*e^(x²)
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


def pack(read_as, subject, concepts, hints, final, check, note="", steps=None):
    return {"read_as": read_as, "subject": subject, "ambiguity_note": note,
            "concepts": [{"name": n, "meaning": m} for n, m in concepts],
            "hints": [clip(h) for h in hints], "final_answer": final, "check": check,
            "steps": steps or [f"Answer: {final}"]}


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
    sup = lambda o: " ".join(f"{s}{str(k).translate(SUP)}" for s, k in ((s, o[s]) for s in ordered(o)))
    steps = [f"Electron configuration of {label}", f"{sym} has Z = {z}, so {n_el} electrons to place.",
             "Aufbau fill order: " + " ".join(upto) + "."]
    if charge <= 0:
        if charge < 0:
            steps.append(f"Anion {label}: {abs(charge)} extra e⁻ are added, so fill {n_el} in total.")
        steps.append("Fill in that order, max 2 e⁻ per orbital (s 2, p 6, d 10, f 14):")
        steps.append(sup(madelung(n_el)))
        if exc:
            steps.append(f"Exception: {sym} is more stable with half-filled or full d/f subshells, so it is")
            steps.append(sup(occ))
    else:
        neutral = config_for(z, 0)
        steps.append("Neutral atom: " + sup(neutral))
        gone = [f"{neutral[s] - occ.get(s, 0)} from {s}" for s in ordered(neutral) if neutral[s] != occ.get(s, 0)]
        steps.append(f"Cation {label}: remove {charge} e⁻ from the highest shell first ({', '.join(gone)}):")
        steps.append(sup(occ))

    def boxes(sub, e):
        n_orb = 2 * L[sub[1]] + 1
        return "".join("[↑↓]" if i < e - n_orb else "[↑]" if i < min(e, n_orb) else "[ ]" for i in range(n_orb))
    steps.append("Hund's rule: " + "  ".join(f"{s} {boxes(s, rest[s])}" for s in ordered(rest)) if rest else "Hund's rule: all orbitals full.")
    steps += [f"Unpaired electrons: {unpaired(occ)}.", f"Noble-gas shorthand: {config_text(occ)}", f"Answer: {final.split('   (')[0]}"]
    return pack(f"Electron configuration of {label} (Z = {z})", "Chemistry", concepts, h, final, check, steps=steps)


# ---------------------------------------------------------------- calculus
def _unwrap(rule, const=1):
    """Find the most informative step in a manualintegrate rule tree -> (rule, outer constant)."""
    name = type(rule).__name__
    if name in ("URule", "PartsRule", "TrigSubstitutionRule", "PartialFractionsRule"):
        return rule, const
    if name == "ConstantTimesRule":
        return _unwrap(rule.substep, const * rule.constant)
    if name == "AlternativeRule":
        found = [rc for rc in (_unwrap(a, const) for a in rule.alternatives) if rc[0] is not None]
        urules = [rc for rc in found if type(rc[0]).__name__ == "URule"]
        if urules:  # the textbook substitution is the simplest u
            return min(urules, key=lambda rc: sp.count_ops(rc[0].u_func))
        return found[0] if found else (None, 1)
    sub = getattr(rule, "substep", None)
    if sub is not None:
        return _unwrap(sub, const)
    for sub in getattr(rule, "substeps", None) or []:
        rc = _unwrap(sub, const)
        if rc[0] is not None:
            return rc
    return None, 1


def _is_antiderivative(f, F, var):
    return verify.verify({"kind": "integral", "expr": str(f), "result": str(F), "var": str(var)})["status"] == "pass"


def _integral_steps(f, F, var, step, const):
    """Worked solution lines + an antiderivative consistent with them (verified)."""
    kind = type(step).__name__ if step is not None else ""
    u_sym = sp.Symbol("u")
    out = [f"Evaluate ∫ {fmt(f)} d{var}"]
    used = ""
    if f.is_Add and len(f.args) > 1:
        used = "sum"
        out.append("It is a sum, so integrate term by term:")
        parts = [sp.integrate(t, var) for t in f.args]
        for t, P in zip(f.args, parts):
            out.append(f"∫ {fmt(t)} d{var} = {fmt(P)}")
        Fs = sp.Add(*parts)
        F = Fs if _is_antiderivative(f, Fs, var) else F
    elif kind == "URule":
        uv, u = step.u_var, step.u_func
        du = sp.diff(u, var)
        inner = sp.simplify(const * step.substep.integrand)
        Fu = sp.integrate(inner, uv)
        Fb = Fu.subs(uv, u)
        if _is_antiderivative(f, Fb, var):  # only narrate a substitution that really solves the whole integral
            used, F = "URule", Fb
            out += [f"Substitution: let u = {fmt(u)}.", f"Then du = {fmt(du)} d{var}.",
                    f"The integral becomes ∫ {fmt(inner.subs(uv, u_sym))} du.",
                    f"Integrate in u: {fmt(Fu.subs(uv, u_sym))} + C.", f"Back-substitute u = {fmt(u)}."]
    elif kind == "PartsRule":
        u, dv = step.u, step.dv
        du, v = sp.diff(u, var), sp.integrate(dv, var)
        rest = sp.simplify(v * du)
        rest_int = sp.integrate(rest, var)
        Fp = const * (u * v - rest_int)
        if _is_antiderivative(f, Fp, var):
            used, F = "PartsRule", Fp
            out += ["Integration by parts: ∫u dv = u·v − ∫v du.",
                    f"Let u = {fmt(u)}, dv = {fmt(dv)} d{var}.", f"Then du = {fmt(du)} d{var}, v = {fmt(v)}.",
                    f"So the integral = {fmt(u * v)} − ∫ {fmt(rest)} d{var}.",
                    f"The remaining integral is {fmt(rest_int)}."]
            if const != 1:
                out.insert(1, f"Constant factor {fmt(const)} stays in front.")
    elif kind in ("TrigSubstitutionRule", "PartialFractionsRule"):
        used = kind
        out += ["Method: " + ("trig substitution." if kind.startswith("Trig") else "partial fractions."),
                "Do the substitution/decomposition, integrate each piece, convert back."]
    if not used:
        if f.is_Mul or f.is_Pow or f.has(sp.sin, sp.cos, sp.tan):
            out.append("Rewrite with an algebra or trig identity, then integrate with standard forms.")
        out.append(f"Standard forms give ∫ {fmt(f)} d{var} = {fmt(F)} + C.")
    out.append(f"Answer: {fmt(F)} + C")
    return out, F, used


def solve_integral(text: str) -> dict:
    t = text.strip()
    if re.search(r"∫\s*[_^]|from\s+-?\w+\s+to\s|definite", t, re.I):
        raise Unsupported("definite integrals aren't supported offline yet")
    m = (re.search(r"(?:∫|integral\s+of|integrate)\s*:?\s*(.*?)\s*d([a-z])\s*$", t, re.I | re.S)
         or re.search(r"^[JfS]?\s*(.*?)\s*d([a-z])\s*$", t, re.S))
    if not m:
        m2 = re.search(r"(?:integral\s+of|integrate)\s*:?\s*(.+)$", t, re.I | re.S)
        if not m2:
            raise Unsupported("couldn't find the integrand and d-variable")
        m = m2
        var = sp.Symbol("x")
        f = to_sympy(strip_outer(m.group(1)))
    else:
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
        steps = [f"Evaluate ∫ {fmt(f)} d{var}", "This integrand has no elementary antiderivative:",
                 "no combination of polynomials, e^x, logs and trig gives it.",
                 f"In special functions: {fmt(F)} + C" if not F.has(sp.Integral) else "SymPy found no closed form.",
                 "Check the problem: is a factor missing (like 2x in front of e^(x²))?"]
        return pack(read, "Calculus", [("Non-elementary integral", "Some integrals can't be written with elementary functions.")],
                    hints, final, check, note="This integrand has no elementary antiderivative.", steps=steps)
    try:
        step, const = _unwrap(integral_steps(f, var))
    except Exception:
        step, const = None, 1
    steps, F, kind = _integral_steps(f, F, var, step, const)
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
    return pack(read, "Calculus", concepts, hints, f"{fmt(F)} + C", {"kind": "integral", "expr": str(f), "result": str(F), "var": str(var)}, steps=steps)


def _classify(f, v):
    """-> (rule kind, extra info, the sub-expression that rule applies to)."""
    if f.is_Add:
        dep = [a for a in f.args if a.has(v)]
        if len(dep) > 1:
            return "sum", None, f
        return _classify(dep[0], v) if dep else ("const", None, f)
    if f.is_Mul:
        dep = [a for a in f.args if a.has(v)]
        if len(dep) >= 2:
            quo = any(a.is_Pow and a.exp.is_negative for a in dep)
            return ("quotient" if quo else "product"), None, f
        return _classify(dep[0], v) if dep else ("const", None, f)
    if f.is_Pow:
        if f.exp.has(v):
            return ("expo" if not f.base.has(v) else "logdiff"), None, f
        return ("power", None, f) if f.base == v else ("chain", (f"power {fmt(f.exp)}", f.base), f)
    if f.is_Function and f.args:
        return ("standard", None, f) if f.args[0] == v else ("chain", (f.func.__name__, f.args[0]), f)
    return "standard", None, f


def _diff_steps(f, var, kind, extra, core, ans):
    out = [f"Differentiate d/d{var} [ {fmt(f)} ]"]
    if core != f:
        out.append(f"Constants in front or added vanish or stay, so work on {fmt(core)}.")
    if kind == "chain":
        g = sp.Symbol("g")
        outer = g ** core.exp if core.is_Pow else core.func(g)
        d_out, d_in = sp.diff(outer, g), sp.diff(extra[1], var)
        out += [f"Chain rule. Outer function: {fmt(outer)}, inner g = {fmt(extra[1])}.",
                f"Outer derivative: d/dg {fmt(outer)} = {fmt(d_out)}.",
                f"Inner derivative: g' = {fmt(d_in)}.",
                f"Multiply: {fmt(d_out.subs(g, extra[1]))} · {fmt(d_in)}."]
    elif kind == "product":
        dep = [a for a in core.args if a.has(var)]
        u, v = dep[0], sp.Mul(*[a for a in core.args if a is not dep[0]])
        out += ["Product rule: (u·v)' = u'·v + u·v'.", f"u = {fmt(u)}, v = {fmt(v)}.",
                f"u' = {fmt(sp.diff(u, var))}, v' = {fmt(sp.diff(v, var))}.",
                f"So the derivative is {fmt(sp.diff(u, var) * v)} + {fmt(u * sp.diff(v, var))}."]
    elif kind == "quotient":
        num, den = sp.fraction(sp.together(core))
        out += ["Quotient rule: (u/v)' = (u'·v − u·v') / v².", f"u = {fmt(num)}, v = {fmt(den)}.",
                f"u' = {fmt(sp.diff(num, var))}, v' = {fmt(sp.diff(den, var))}.",
                f"Numerator: {fmt(sp.diff(num, var) * den - num * sp.diff(den, var))}, over ({fmt(den)})²."]
    elif kind == "sum":
        out.append("It is a sum: differentiate each term.")
        out += [f"d/d{var} {fmt(t)} = {fmt(sp.diff(t, var))}" for t in core.args]
    elif kind == "logdiff":
        lg = sp.expand_log(sp.log(core), force=True)
        out += [f"Variable base and exponent: take ln. ln y = {fmt(lg)}.",
                f"Differentiate: y'/y = {fmt(sp.diff(lg, var))}.", f"So y' = y · ({fmt(sp.diff(lg, var))})."]
    elif kind == "power":
        out.append(f"Power rule: d/d{var} {var}^n = n·{var}^(n−1), so d/d{var} {fmt(core)} = {fmt(sp.diff(core, var))}.")
    elif kind == "expo":
        out.append(f"Exponential rule: d/d{var} a^{var} = a^{var}·ln(a), so d/d{var} {fmt(core)} = {fmt(sp.diff(core, var))}.")
    elif kind == "const":
        out.append("Nothing depends on the variable, so the derivative is 0.")
    else:
        out.append(f"Standard derivative: d/d{var} {fmt(core)} = {fmt(sp.diff(core, var))}.")
    out.append(f"Answer: {fmt(ans)}")
    return out


def solve_derivative(text: str) -> dict:
    t = text.strip()
    m = (re.search(r"d\s*/\s*d([a-z])\s*(.+)$", t, re.S)
         or re.search(r"(?:derivative\s+of|differentiate)\s*:?\s*(.+?)(?:\s+with respect to\s+([a-z]))?\s*$", t, re.I | re.S))
    if not m:
        raise Unsupported("couldn't find what to differentiate")
    if m.re.pattern.startswith("d\\s*/"):
        var, body = sp.Symbol(m.group(1)), m.group(2)
    else:
        body = m.group(1)
        var = sp.Symbol(m.group(2) or "x")
    body = re.sub(r"^\s*[a-z]\s*\(\s*[a-z]\s*\)\s*=", "", body)
    f = to_sympy(strip_outer(body))
    kind, extra, core = _classify(f, var)
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
                {"kind": "derivative", "expr": str(f), "result": str(ans), "var": str(var)},
                steps=_diff_steps(f, var, kind, extra, core, ans))


def solve_limit(text: str) -> dict:
    m = re.search(r"lim(?:it)?\s*[_{(]*\s*([a-z])\s*(?:→|->|to)\s*([-+]?(?:\d+(?:\.\d+)?|∞|oo|inf(?:inity)?)|[-+]?[a-z])\s*[)}]*\s*(?:of)?\s*(.+)$", text.strip(), re.I | re.S)
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
    steps = [f"Evaluate lim {var}→{fmt(pt)} of {fmt(f)}"]
    if not indeterminate:
        steps += [f"Substitute {var} = {fmt(pt)}: {fmt(direct)}.", "It is defined and finite, so that is the limit."]
    else:
        steps.append(f"Substituting {var} = {fmt(pt)} gives an indeterminate form, so simplify first.")
        num, den = sp.fraction(sp.together(f))
        cancelled = sp.cancel(f)
        try:
            ok_cancel = cancelled != f and pt != sp.oo and sp.simplify(cancelled.subs(var, pt) - L) == 0
        except Exception:
            ok_cancel = False
        lhop_ok = False
        if not ok_cancel and den != 1:
            try:
                ratio = sp.diff(num, var) / sp.diff(den, var)
                lhop_ok = abs(float(sp.N(sp.limit(ratio, var, pt) - L))) < 1e-9
            except Exception:
                lhop_ok = False
        if ok_cancel:
            steps += [f"Cancel common factors: {fmt(cancelled)}.", f"Now substitute {var} = {fmt(pt)}: {fmt(cancelled.subs(var, pt))}."]
        elif lhop_ok:
            steps += ["Both top and bottom → 0 or ∞, so use L'Hôpital: lim f/g = lim f'/g'.",
                      f"f' = {fmt(sp.diff(num, var))}, g' = {fmt(sp.diff(den, var))}.",
                      f"Evaluate lim of {fmt(ratio)} = {fmt(L)}."]
        elif f.has(sp.sin) and pt == 0:
            steps.append("Standard limit: sin(u)/u → 1 as u → 0 (adjust for any constant factor).")
        else:
            steps.append("Use a standard limit or series expansion.")
    steps.append(f"Answer: {fmt(L)}")
    return pack(f"lim {var}→{fmt(pt)} of {fmt(f)}", "Calculus", [("Limits", "Value the function approaches near a point."),
                ("L'Hôpital's rule", "0/0 or ∞/∞: differentiate top and bottom.")], hints, final, check, steps=steps)


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
        # decimals in the problem make SymPy return Floats: turn them back into exact numbers
        exact = [sp.nsimplify(r, rational=True, tolerance=1e-9) if r.has(sp.Float) else r for r in sols]
        roots = sorted(exact, key=lambda r: float(sp.N(r)))
        final = " or ".join(f"{v} = {fmt(r)}" for r in roots)
        check = {"kind": "equation", "expr": f"{lhs} = {rhs}", "result": ", ".join(str(r) for r in roots), "var": str(v)}
    elif sols is sp.S.EmptySet:
        final, check = "No real solutions.", {"kind": "none"}
    else:
        raise Unsupported("couldn't solve that equation in closed form")
    steps = [f"Solve {fmt(lhs)} = {fmt(rhs)}"]
    if deg == 2:
        a, b, c = sp.Poly(expr, v).all_coeffs()
        D = b ** 2 - 4 * a * c
        steps += [f"Standard form: {fmt(sp.expand(expr))} = 0.", f"a = {fmt(a)}, b = {fmt(b)}, c = {fmt(c)}.",
                  f"Discriminant D = b² − 4ac = {fmt(D)}.",
                  "D > 0: two real roots." if D > 0 else "D = 0: one repeated root." if D == 0 else "D < 0: no real roots.",
                  f"{v} = (−b ± √D) / 2a."]
    elif deg == 1:
        steps += [f"Collect terms: {fmt(sp.expand(expr))} = 0.", f"Isolate {v} by undoing the operations."]
    elif deg:
        steps += [f"Move everything to one side: {fmt(sp.expand(expr))} = 0.", f"Factor: {fmt(sp.factor(expr))} = 0.",
                  "Set each factor to zero."]
    else:
        steps.append("Isolate the unknown and solve; check each candidate for extraneous roots.")
    steps.append(f"Answer: {final}")
    return pack(f"Solve {fmt(lhs)} = {fmt(rhs)}", "Algebra", concepts, hints, final, check, steps=steps)


# ---------------------------------------------------------------- dispatch
FULLWIDTH = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
FULLWIDTH[0x3000] = 0x20


def defullwidth(text: str) -> str:
    """OCR often returns fullwidth ASCII: （x）＝２ -> (x)=2. Superscripts like ² are left alone."""
    return text.translate(FULLWIDTH)


LEAD = re.compile(r"^(?:q(?:uestion)?\s*\d+\s*[:.)]|\(?\d+[.)]\s+|\([a-z]\)\s*|[a-z][.)]\s+)\s*", re.I)


def clean_line(text: str) -> str:
    """Strip numbering ('2.', 'Q3:', '(a)') and trailing punctuation that OCR/typing leaves around a problem."""
    t = defullwidth(text).strip()
    t = LEAD.sub("", t)
    return t.rstrip(".,;:!? \t")


def solve(text: str) -> dict:
    t = clean_line(text)
    lo = t.lower()
    if re.search(r"electron(?:ic)?\s+config|e-?\s*config|configuration of", lo):
        return solve_config(t)
    if re.search(r"\blim(?:it)?\b|\blim(?:it)?\s*[_{(]*\s*[a-z]\s*(?:→|->|to\b)", lo):
        return solve_limit(t)
    if "∫" in t or re.search(r"\bintegra", lo) or (re.search(r"\bd[xyt]\s*$", t) and "=" not in t and not re.search(r"d\s*/\s*d", t)):
        return solve_integral(t)
    if re.search(r"d\s*/\s*d[a-z]|derivative|differentiate", lo):
        return solve_derivative(t)
    if "=" in t:
        body = re.sub(r"^\s*(?:please\s+)?solve", "", t, flags=re.I)
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


class OCRUnavailable(Exception):
    pass


def repair_ocr(text: str) -> str:
    """Fix the confusions OCR makes on maths (applied per line)."""
    out = []
    for line in defullwidth(text).splitlines():
        t = line.strip().replace("~", "^")
        t = re.sub(r"(?<![A-Za-z])([xyzt])(\d+)(?![\d.])", r"\1^\2", t)      # x3 -> x^3 (lost superscript)
        if re.search(r"(?:\s|\))d[xyt]\s*$", t):
            t = re.sub(r"^(?:\(?\d{1,2}[.)]\s*)?[{|JfSʃ/Il]\s*", "∫ ", t)      # lost integral sign (maybe glued to a number)
        if t:
            out.append(t)
    return "\n".join(out)


def _ocr_rapid(image_bytes: bytes) -> str:
    global _ocr
    from rapidocr_onnxruntime import RapidOCR  # ImportError -> try the next backend
    _ocr = _ocr or RapidOCR()
    result, _ = _ocr(image_bytes)
    return "\n".join(r[1] for r in (result or []))


def _ocr_tesseract(image_bytes: bytes) -> str:
    """Tesseract CLI (Termux: pkg install tesseract). Light preprocessing if Pillow is present."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("tesseract")
    if not exe:
        raise ImportError("tesseract not installed")
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/in.png"
        try:
            import io

            from PIL import Image, ImageOps
            im = ImageOps.autocontrast(ImageOps.grayscale(Image.open(io.BytesIO(image_bytes))))
            if im.width < 1400:
                im = im.resize((im.width * 2, im.height * 2))
            im.save(path)
        except ImportError:
            with open(path, "wb") as fh:
                fh.write(image_bytes)
        r = subprocess.run([exe, path, "stdout", "--psm", "6"], capture_output=True, text=True, timeout=30)
        return r.stdout


BACKENDS = {"rapidocr": _ocr_rapid, "tesseract": _ocr_tesseract}


def ocr_backend() -> str | None:
    """Name of the first usable OCR backend, or None."""
    import importlib.util
    import shutil
    if importlib.util.find_spec("rapidocr_onnxruntime"):
        return "rapidocr"
    return "tesseract" if shutil.which("tesseract") else None


def ocr(image_bytes: bytes) -> str:
    """Read text from an image (lines separated by newlines). Handwriting is weak; printed text is fine."""
    name = ocr_backend()
    if name is None:
        raise OCRUnavailable("no OCR installed: pkg install tesseract (Termux) or pip install rapidocr-onnxruntime")
    return repair_ocr(BACKENDS[name](image_bytes))


# ---------------------------------------------------------------- one call for everything
def candidates(text: str):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    yield from lines
    yield from (lines[i] + " " + lines[i + 1] for i in range(len(lines) - 1))
    if len(lines) > 2:
        yield " ".join(lines)


def solve_text(text: str, timeout: float = 12.0) -> dict:
    """Never raises. Tries each OCR line, then neighbouring pairs, then the whole text."""
    why = "nothing readable"
    for c in candidates(text):
        try:
            data = solve_safely(c, timeout)
        except Unsupported as e:
            why = str(e)
            continue
        r = verify.verify(data.get("check"))
        return {"ok": True, **data, "verified": r["status"], "verify_note": r["note"]}
    return {"ok": False, "reason": why, "read": text.strip()}
