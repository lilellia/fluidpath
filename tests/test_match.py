from fluidpath import Path


def test_match_true_with_full() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.match("root/.*f.*xt")


def test_match_true_without_full() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.match("f.*xt", full=False)


def test_match_true_with_full_case_insensitive() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.match("ROOT/.*F.*xt", case_sensitive=False)


def test_match_true_without_full_case_insensitive() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.match(".*F.*xt", full=False, case_sensitive=False)


def test_glob_match_true_with_full() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.glob_match("root/*f*xt")


def test_glob_match_true_without_full() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.glob_match("f*xt", full=False)


def test_glob_match_true_with_full_case_insensitive() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.glob_match("ROOT/*F*xt", case_sensitive=False)


def test_glob_match_true_without_full_case_insensitive() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.glob_match("*F*xt", full=False, case_sensitive=False)
