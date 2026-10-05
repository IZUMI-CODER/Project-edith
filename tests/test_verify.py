import verify as v

S = lambda r: r["status"]


def test_integral_pass_and_fail():
    assert S(v.verify({"kind": "integral", "expr": "2*x*exp(x^2)", "result": "exp(x^2) + C"})) == "pass"
    assert S(v.verify({"kind": "integral", "expr": "2x e^(x²)".replace("e^", "exp"), "result": "x^2"})) in ("fail", "skipped")
    assert S(v.verify({"kind": "integral", "expr": "2*x*exp(x^2)", "result": "exp(x^2)/2"})) == "fail"


def test_derivative_and_unicode():
    assert S(v.verify({"kind": "derivative", "expr": "sin(x³)", "result": "3x²·cos(x³)"})) == "pass"
    assert S(v.verify({"kind": "derivative", "expr": "sin(x^3)", "result": "cos(x^3)"})) == "fail"


def test_equation_roots_and_completeness():
    c = {"kind": "equation", "expr": "x^2 - 5x + 6 = 0", "result": "2, 3"}
    assert S(v.verify(c)) == "pass"
    assert S(v.verify({**c, "result": "2, 4"})) == "fail"
    r = v.verify({**c, "result": "2"})
    assert S(r) == "fail" and "missing" in r["note"]


def test_limit():
    assert S(v.verify({"kind": "limit", "expr": "sin(x)/x", "point": "0", "result": "1"})) == "pass"
    assert S(v.verify({"kind": "limit", "expr": "sin(x)/x", "point": "0", "result": "0"})) == "fail"
    assert S(v.verify({"kind": "limit", "expr": "(1+1/x)^x", "point": "oo", "result": "2.718281828"})) == "pass"


def test_electron_count():
    assert S(v.verify({"kind": "electron_count", "z": 26, "config": "[Ar] 4s2 3d6"})) == "pass"
    assert S(v.verify({"kind": "electron_count", "z": 24, "config": "[Ar] 4s1 3d5"})) == "pass"
    assert S(v.verify({"kind": "electron_count", "z": 26, "config": "[Ar] 4s2 3d7"})) == "fail"
    assert S(v.verify({"kind": "electron_count", "z": 26, "config": "[Ar] 4s3 3d5"})) == "fail"  # Pauli
    assert S(v.verify({"kind": "electron_count", "z": 26, "charge": 2, "config": "[Ar] 3d6"})) == "pass"


def test_untrusted_input_is_never_executed():
    for evil in ("__import__('os').system('echo hi')", "x.__class__", "open('/etc/passwd')", "lambda: 1"):
        assert S(v.verify({"kind": "derivative", "expr": evil, "result": "1"})) == "skipped"
    assert S(v.verify({"kind": "derivative", "expr": "foo(x)", "result": "1"})) == "skipped"
    assert S(v.verify({"kind": "bogus"})) == "skipped"
    assert S(v.verify(None)) == "skipped"
    assert S(v.verify({"kind": "integral"})) == "skipped"
