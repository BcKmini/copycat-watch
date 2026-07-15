"""금액·판매가 표기 헬퍼.

내용증명·손해배상 문서는 금액을 숫자와 한글로 병기하는 관행이 있어
(예: 123,000원(금 일십이만삼천원)) 정식 한글 금액 표기를 생성한다.
"""
import re

from core.config import ASSUMED_MONTHLY_SALES

_KOR_DIGITS = "영일이삼사오육칠팔구"
_KOR_SMALL_UNITS = ["", "십", "백", "천"]
_KOR_BIG_UNITS = ["", "만", "억", "조"]


def parse_price(price_str: str) -> int:
    digits = re.sub(r"[^0-9]", "", price_str)
    return int(digits) if digits else 0


def estimate_damage(price_str: str) -> int:
    return parse_price(price_str) * ASSUMED_MONTHLY_SALES


def number_to_korean(n: int) -> str:
    if n == 0:
        return "영"
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        digits = [int(d) for d in str(g).zfill(4)]
        s = "".join(
            _KOR_DIGITS[d] + _KOR_SMALL_UNITS[3 - j]
            for j, d in enumerate(digits)
            if d != 0
        )
        parts.append(s + _KOR_BIG_UNITS[i])
    return "".join(parts)


def format_amount(n: int) -> str:
    return f"{n:,}원(금 {number_to_korean(n)}원)"
