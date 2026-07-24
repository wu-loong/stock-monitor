def to_secid(code: str) -> str:
    """6 位 A 股代码 → 带交易所前缀的 secid。
    上交所:6 开头(主板 60x)、688(科创)、900(B股);其余归深交所(000/001/002/003/300/301)。
    """
    code = str(code).zfill(6)
    if code[0] == "6" or code[:3] in ("688", "900"):
        return "sh" + code
    return "sz" + code
