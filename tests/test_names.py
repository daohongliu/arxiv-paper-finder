from __future__ import annotations

from arxiv_finder.names import any_plausible_chinese_author, name_plausibly_chinese


def test_chinese_surname_kept():
    assert any_plausible_chinese_author(["Minlie Huang", "John Smith"]) is True
    assert any_plausible_chinese_author(["Wei Zhang"]) is True
    assert any_plausible_chinese_author(["Aishan Liu", "Xianglong Liu"]) is True
    assert any_plausible_chinese_author(["Tie-Jun Zhang"]) is True


def test_cantonese_and_hk_romanizations():
    assert name_plausibly_chinese("Dit-Yan Yeung") is True
    assert name_plausibly_chinese("Siu-Ming Yiu") is True
    assert any_plausible_chinese_author(["Wing-Kin Chan"]) is True


def test_clearly_non_chinese_excluded():
    assert any_plausible_chinese_author(["Yann LeCun", "Geoffrey Hinton"]) is False
    assert any_plausible_chinese_author(["Ilya Sutskever", "Andrej Karpathy"]) is False
    assert any_plausible_chinese_author(["Alice Johnson", "Bob Williams"]) is False


def test_lax_on_ambiguity():
    # single-token / unusual names can't be judged -> keep
    assert name_plausibly_chinese("A") is None
    assert any_plausible_chinese_author(["A"]) is True
    # CJK characters in metadata -> keep
    assert any_plausible_chinese_author(["张伟", "李四"]) is True
    # no author info -> keep
    assert any_plausible_chinese_author([]) is True


def test_name_normalization():
    assert name_plausibly_chinese("ZHANG Wei") is True
    assert name_plausibly_chinese("Zhang, Wei") is True
    assert name_plausibly_chinese("José García-Márquez") is False
