import pytest

import offline
import verify

S = offline.solve_safely


@pytest.mark.parametrize("problem,answer", [
    ("∫ 2x·e^(x²) dx", "e^(x²) + C"),
    ("∫ x e^x dx", "(x - 1)·e^(x) + C"),
    ("integrate x^3 + 2x dx", "x⁴/4 + x² + C"),
    ("d/dx [ sin(x³) ]", "3x²cos(x³)"),
    ("lim x→0 of sin(x)/x", "lim = 1"),
    ("lim x->2 (x^2-4)/(x-2)", "lim = 4"),
    ("Solve x² - 5x + 6 = 0", "x = 2 or x = 3"),
    ("Solve 2x + 3 = 11", "x = 4"),
    ("Write the electron configuration of Fe (Z=26).", "Fe: [Ar] 4s² 3d⁶"),
    ("electron configuration of Cr", "Cr: [Ar] 4s¹ 3d⁵"),
    ("electron configuration of Cu", "Cu: [Ar] 4s¹ 3d¹⁰"),
    ("electron config of Pd", "Pd: [Kr] 4d¹⁰"),
    ("electron configuration of Au", "Au: [Xe] 6s¹ 4f¹⁴ 5d¹⁰"),
    ("electron configuration of Fe2+", "Fe2+: [Ar] 3d⁶"),
    ("electron configuration of Fe3+", "Fe3+: [Ar] 3d⁵"),
    ("electron configuration of Cu+", "Cu+: [Ar] 3d¹⁰"),
    ("electron configuration of Sn2+", "Sn2+: [Kr] 5s² 4d¹⁰"),
    ("electron configuration of O2-", "O2-: [Ne]"),
    ("electron configuration of iron", "Fe: [Ar] 4s² 3d⁶"),
    ("electron configuration of Z = 11", "Na: [Ne] 3s¹"),
])
def test_known_answers(problem, answer):
    r = S(problem)
    assert r["final_answer"].startswith(answer)
    assert verify.verify(r["check"])["status"] == "pass"


def test_hints_fit_the_glasses_and_do_not_leak():
    for p in ["∫ 2x·e^(x²) dx", "∫ x*cos(x) dx", "d/dx (x^2+1)/(x-3)", "Solve x² - 5x + 6 = 0",
              "electron configuration of Fe2+", "electron configuration of Cr", "lim x->2 (x^2-4)/(x-2)"]:
        r = S(p)
        assert 4 <= len(r["hints"]) <= 8
        assert all(len(h) <= 90 for h in r["hints"]), p
        assert r["final_answer"] not in r["hints"]


def test_method_choice_matches_the_math():
    assert "u-substitution" in S("∫ 2x·e^(x²) dx")["hints"][1]
    assert "by parts" in S("∫ x*cos(x) dx")["hints"][0]
    assert "u = x²" in S("∫ 2x·e^(x²) dx")["hints"][2]      # the textbook u, not exp(x²)
    assert "product rule" in S("d/dx x^2*ln(x)")["hints"][0]
    assert "quotient rule" in S("d/dx (x^2+1)/(x-3)")["hints"][0]
    assert "chain rule" in S("d/dx sin(x^3)")["hints"][2].lower()


def test_nonelementary_integral_is_flagged():
    r = S("∫ e^(x²) dx")
    assert "no elementary antiderivative" in r["ambiguity_note"].lower()
    assert "erfi" in r["final_answer"]


def test_exception_hint_only_for_exceptions():
    assert any("exception" in h for h in S("electron configuration of Cr")["hints"])
    assert not any("exception" in h for h in S("electron configuration of Fe")["hints"])


@pytest.mark.parametrize("bad", ["How many moles in 36 g of water?", "How many moles are in 36 g of H2O? (M = 18 g/mol)", "∫_0^1 x dx", "hello", "x = y + z", "electron configuration of banana"])
def test_unsupported_is_reported_not_guessed(bad):
    with pytest.raises(offline.Unsupported):
        S(bad)


@pytest.mark.parametrize("evil", ["∫ __import__('os').system('echo hi') dx", "d/dx open('/etc/passwd')", "solve x.__class__ = 1"])
def test_hostile_input_never_executes(evil):
    with pytest.raises(offline.Unsupported):
        S(evil)


@pytest.mark.parametrize("ocr_text,fixed", [
    ("{ 2x·e~(x²) dx", "∫ 2x·e^(x²) dx"),
    ("d/dx [ sin(x3) ]", "d/dx [ sin(x^3) ]"),
    ("J x e~x dx", "∫ x e^x dx"),
    ("Solve x2 - 5x + 6 = 0", "Solve x^2 - 5x + 6 = 0"),
    ("Write the electron configuration of Fe (Z=26).", "Write the electron configuration of Fe (Z=26)."),
    ("f(x) = 3x", "f(x) = 3x"),                       # must not become an integral
])
def test_ocr_repair(ocr_text, fixed):
    assert offline.repair_ocr(ocr_text) == fixed


def test_word_problem_message_is_clear():
    with pytest.raises(offline.Unsupported, match="word problems"):
        S("A car goes 60 km in 2 hours = what speed")
    assert S("solve sqrt(x) = 3")["final_answer"] == "x = 9"  # real maths with function names still works
