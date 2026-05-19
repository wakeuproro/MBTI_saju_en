"""
📿 사주 계산 자동 검증 스크립트
- 라이브러리 직접 호출 결과를 정답으로 간주 (한국천문연구원 데이터)
- 우리 calc_pillars_accurate() 결과와 비교
- 다양한 케이스: 양력/음력/자시/절기 경계/연주 경계/윤달
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import calc_pillars_accurate, analyze_oheng, calc_time_pillar
from korean_lunar_calendar import KoreanLunarCalendar
from datetime import date, timedelta


def expected_from_library(year, month, day, hour, calendar_type='solar', is_leap_month=False):
    """라이브러리 직접 호출로 정답 계산 (시주는 별도)"""
    cal = KoreanLunarCalendar()
    if calendar_type == 'lunar':
        cal.setLunarDate(year, month, day, is_leap_month)
        sy, sm, sd = map(int, cal.SolarIsoFormat().split('-'))
    else:
        sy, sm, sd = year, month, day

    # 자시(23시) 처리
    if hour == 23:
        d = date(sy, sm, sd) + timedelta(days=1)
        sy, sm, sd = d.year, d.month, d.day

    cal2 = KoreanLunarCalendar()
    cal2.setSolarDate(sy, sm, sd)
    gapja = cal2.getGapJaString()
    parts = gapja.replace('년', ' ').replace('월', ' ').replace('일', ' ').split()
    yp = (parts[0][0], parts[0][1])
    mp = (parts[1][0], parts[1][1])
    dp = (parts[2][0], parts[2][1])
    tp = calc_time_pillar(dp[0], hour)
    return yp, mp, dp, tp


def run_tests():
    passed = 0
    failed = 0
    failures = []

    # ─── 다양한 케이스 ───
    cases = []

    # 1) 양력 일반 (10년 단위)
    for y in [1920, 1950, 1970, 1985, 1990, 2000, 2010, 2020, 2024, 2030]:
        cases.append(('solar 일반', y, 5, 15, 14, 'solar', False))

    # 2) 양력 매월 1일 (절기 경계 검증)
    for m in range(1, 13):
        cases.append((f'양력 {m}월 1일 (절기 경계)', 1995, m, 1, 10, 'solar', False))

    # 3) 양력 입춘 직전/직후 (1-2월 초)
    cases.extend([
        ('입춘 직전 (2/3)', 1995, 2, 3, 12, 'solar', False),
        ('입춘 당일 (2/4)', 1995, 2, 4, 12, 'solar', False),
        ('입춘 직후 (2/5)', 1995, 2, 5, 12, 'solar', False),
        ('1월 1일 (작년 연주)', 1995, 1, 1, 12, 'solar', False),
        ('1월 15일 (작년 연주)', 2000, 1, 15, 12, 'solar', False),
    ])

    # 4) 자시 (23시) 케이스
    cases.extend([
        ('자시 23시 양력', 1990, 5, 15, 23, 'solar', False),
        ('자시 0시 양력',  1990, 5, 15, 0, 'solar', False),
        ('자시 23시 음력', 1985, 2, 24, 23, 'lunar', False),
        ('자시 0시 양력 (월말)', 1990, 5, 31, 0, 'solar', False),
        ('자시 23시 양력 (월말)', 1990, 5, 31, 23, 'solar', False),
    ])

    # 5) 모든 시진 (시주 검증)
    for h in range(0, 24, 2):
        cases.append((f'양력 {h}시 시주', 2000, 6, 15, h, 'solar', False))

    # 6) 음력 케이스
    cases.extend([
        ('음력 1985-02-24', 1985, 2, 24, 14, 'lunar', False),
        ('음력 1990-04-21', 1990, 4, 21, 10, 'lunar', False),
        ('음력 2000-01-01 (양력 2/5)', 2000, 1, 1, 12, 'lunar', False),
        ('음력 2020-04-15 (윤달!)', 2020, 4, 15, 14, 'lunar', True),
    ])

    # 7) 음력 12/30 (양력 다음 해) 케이스
    cases.extend([
        ('음력 1999-11-25 (양력 2000)', 1999, 11, 25, 12, 'lunar', False),
    ])

    # ─── 실행 ───
    print(f"\n{'='*70}")
    print(f"📿 사주 계산 정확도 검증 — 총 {len(cases)}개 케이스")
    print('='*70)

    for desc, y, m, d, h, cal_type, leap in cases:
        try:
            actual = calc_pillars_accurate(y, m, d, h, cal_type, leap)
            expected = expected_from_library(y, m, d, h, cal_type, leap)
            if actual == expected:
                passed += 1
            else:
                failed += 1
                failures.append({
                    'desc': desc,
                    'input': f'{y}-{m:02d}-{d:02d} {h}시 ({cal_type})',
                    'actual': '/'.join(f'{p[0]}{p[1]}' for p in actual),
                    'expected': '/'.join(f'{p[0]}{p[1]}' for p in expected),
                })
        except Exception as e:
            failed += 1
            failures.append({'desc': desc, 'input': f'{y}-{m}-{d} {h}시', 'error': str(e)[:60]})

    print(f'\n✓ PASS: {passed}/{len(cases)} ({passed*100/len(cases):.1f}%)')
    print(f'✗ FAIL: {failed}/{len(cases)}')

    if failures:
        print(f'\n{"─"*70}')
        print('실패 케이스:')
        print('─'*70)
        for f in failures[:20]:
            print(f"  [{f['desc']}] {f['input']}")
            if 'error' in f:
                print(f"    ERROR: {f['error']}")
            else:
                print(f"    실제: {f['actual']}")
                print(f"    정답: {f['expected']}")

    return passed, failed, failures


if __name__ == '__main__':
    p, f, _ = run_tests()
    sys.exit(0 if f == 0 else 1)
