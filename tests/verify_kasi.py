"""
🌐 KASI 공식 데이터 회귀 테스트
- 한국천문연구원 월별 음양력 표의 알려진 케이스와 우리 sxtwl 결과 비교
- 100% 일치해야 함
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from main import calc_pillars_accurate

# KASI 월별 음양력 (https://astro.kasi.re.kr/life/pageView/5) 기준 알려진 정답
# 형식: (양력 YYYY-MM-DD, 일주 갑자)
# 보고서 내 명시적으로 확인된 케이스만 (KASI 공식 표 대조)
KASI_KNOWN = [
    # 2026년 5월 (보고서 검증 완료)
    ('2026-05-01', '을해'),
    ('2026-05-02', '병자'),
    ('2026-05-05', '기묘'),
    # 추가 검증 완료 (한국 표준 만세력)
    ('1990-05-15', '경진'),
    ('1985-04-13', '임오'),
    ('1995-05-15', '병오'),
    ('2000-01-01', '무오'),
    ('2024-02-04', '무술'),  # 입춘 당일
]


def run():
    print(f'\n{"="*60}')
    print(f'🌐 KASI 회귀 테스트 — {len(KASI_KNOWN)}개 케이스')
    print('='*60)
    pass_n, fail_n = 0, 0
    failures = []
    for solar, expected_day_gz in KASI_KNOWN:
        y, m, d = map(int, solar.split('-'))
        try:
            yp, mp, dp, tp = calc_pillars_accurate(y, m, d, 12)
            actual = f'{dp[0]}{dp[1]}'
            if actual == expected_day_gz:
                pass_n += 1
            else:
                fail_n += 1
                failures.append((solar, actual, expected_day_gz))
        except Exception as e:
            fail_n += 1
            failures.append((solar, f'ERR: {str(e)[:60]}', expected_day_gz))

    print(f'\n결과: {pass_n}/{len(KASI_KNOWN)} 통과 ({pass_n*100/len(KASI_KNOWN):.1f}%)')
    if failures:
        print('\n실패:')
        for s, a, e in failures:
            print(f'  {s}: 실제={a}, KASI 기대={e}')
    return pass_n, fail_n


if __name__ == '__main__':
    p, f = run()
    sys.exit(0 if f == 0 else 1)
