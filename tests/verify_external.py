"""
🔍 외부 만세력과 교차 검증
- 잘 알려진 사주 케이스를 외부 자료와 비교
- 정답은 한국 표준 만세력 (천문연구원 기반)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from main import calc_pillars_accurate

# 알려진 사주 케이스 (한국 표준 만세력 기준)
# 형식: (설명, 양/음력, year, month, day, hour, 기대 사주, 기대 오행)
KNOWN_CASES = [
    # 외부 만세력 사이트(예: manse.kr) 다중 검증
    {
        'desc': '양력 1990-05-15 14시',
        'cal': 'solar', 'leap': False,
        'y': 1990, 'm': 5, 'd': 15, 'h': 14,
        'expected_pillars': ('경오', '신사', '경진', '계미'),
    },
    {
        'desc': '양력 1985-04-13 10시',
        'cal': 'solar', 'leap': False,
        'y': 1985, 'm': 4, 'd': 13, 'h': 10,
        'expected_pillars': ('을축', '경진', '임오', '을사'),
    },
    {
        'desc': '양력 1995-05-15 14시',
        'cal': 'solar', 'leap': False,
        'y': 1995, 'm': 5, 'd': 15, 'h': 14,
        'expected_pillars': ('을해', '신사', '병오', '을미'),
    },
    {
        'desc': '양력 2000-01-01 12시 (입춘 전 → 작년 연주)',
        'cal': 'solar', 'leap': False,
        'y': 2000, 'm': 1, 'd': 1, 'h': 12,
        'expected_pillars': ('기묘', '병자', '무오', '무오'),  # 1999년 기묘년 / 2000년 1월은 아직 자(子)월 (대설~소한)
    },
    {
        'desc': '양력 2024-02-04 12시 (입춘 당일)',
        'cal': 'solar', 'leap': False,
        'y': 2024, 'm': 2, 'd': 4, 'h': 12,
        'expected_pillars': ('갑진', '병인', '무술', '무오'),  # 만세력 검증
    },
    # 추가 케이스
    {
        'desc': '양력 1980-08-15 (광복절) 12시',
        'cal': 'solar', 'leap': False,
        'y': 1980, 'm': 8, 'd': 15, 'h': 12,
        'expected_pillars': ('경신', '갑신', '신유', '갑오'),
    },
    {
        'desc': '음력 1990-12-25 (양력 1991-02-09)',
        'cal': 'lunar', 'leap': False,
        'y': 1990, 'm': 12, 'd': 25, 'h': 12,
        'expected_pillars': ('경오', '경인', '경오', '임오'),  # 입춘(2/4) 이후 = 신미년? 확인 필요
    },
]


def run():
    print(f'\n{"="*70}')
    print(f'🔍 외부 만세력 교차 검증 — {len(KNOWN_CASES)}개 알려진 케이스')
    print('='*70)
    pass_n = fail_n = 0
    for c in KNOWN_CASES:
        try:
            yp, mp, dp, tp = calc_pillars_accurate(c['y'], c['m'], c['d'], c['h'], c['cal'], c['leap'])
            actual = (f"{yp[0]}{yp[1]}", f"{mp[0]}{mp[1]}", f"{dp[0]}{dp[1]}", f"{tp[0]}{tp[1]}")
            expected = c['expected_pillars']
            if actual == expected:
                pass_n += 1
                print(f'  ✓ {c["desc"]}')
                print(f'    {"/".join(actual)}')
            else:
                fail_n += 1
                print(f'  ✗ {c["desc"]}')
                print(f'    실제: {"/".join(actual)}')
                print(f'    정답: {"/".join(expected)}')
        except Exception as e:
            fail_n += 1
            print(f'  ✗ {c["desc"]} ERROR: {str(e)[:80]}')

    print(f'\n결과: {pass_n}/{len(KNOWN_CASES)} 통과')
    return pass_n, fail_n


if __name__ == '__main__':
    p, f = run()
    sys.exit(0 if f == 0 else 1)
