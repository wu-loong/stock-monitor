from scanner.symbols import to_secid


def test_shanghai_main_board():
    assert to_secid("600000") == "sh600000"


def test_star_board_688():
    assert to_secid("688981") == "sh688981"


def test_shenzhen_main_and_chinext():
    assert to_secid("000001") == "sz000001"
    assert to_secid("300750") == "sz300750"
    assert to_secid("301001") == "sz301001"
