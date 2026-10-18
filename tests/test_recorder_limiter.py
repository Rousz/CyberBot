"""Hız sınırlayıcı: istek aralığı, kayan pencere, öncelik, 429/418 duraklatma."""

import asyncio

from cyberbot.recorder.limiter import RateLimiter, retry_after_s
from tests.recorder_fakes import FakeClock


def make(max_rps=2.0, window_s=300, window_max=700, clock=None):
    return RateLimiter(clock or FakeClock(0), max_rps=max_rps, window_s=window_s, window_max=window_max)


def test_min_gap_between_requests():
    lim = make(max_rps=2.0)
    assert lim.delay_ms(1000) == 0
    lim.record(1000)
    assert lim.delay_ms(1200) == 300  # 500 ms aralık
    assert lim.delay_ms(1500) == 0


def test_sliding_window_cap_and_expiry():
    lim = make(max_rps=1000, window_s=10, window_max=3)
    for t in (0, 1000, 2000):
        assert lim.delay_ms(t) <= 0
        lim.record(t)
    assert lim.delay_ms(3000) == 7000       # en eski istek 10 sn'de pencereden çıkar
    assert lim.delay_ms(10_000) == 0        # t=0 çıktı (kayan pencere, sabit değil)
    assert lim.in_window(10_000) == 2


def test_low_priority_cap_leaves_room_for_live():
    lim = make(max_rps=1000, window_s=10, window_max=5)
    lim.low_cap = 2
    lim.record(0, low=True)
    lim.record(1, low=True)
    assert lim.delay_ms(2, low=True) > 0     # doldurma payı bitti
    assert lim.delay_ms(2, low=False) == 0   # canlı hâlâ gidebilir
    lim.low_cap = 0
    assert lim.delay_ms(50_000, low=True) > 0


def test_live_requests_do_not_consume_backfill_share():
    """low_cap sadece düşük öncelikli istekleri sayar; toplam yine window_max'ı aşamaz."""
    lim = make(max_rps=1000, window_s=10, window_max=5)
    lim.low_cap = 2
    for t in (0, 1, 2):
        lim.record(t)                         # canlı istekler
    assert lim.delay_ms(3, low=True) == 0     # doldurma payı (2) hâlâ boş
    lim.record(3, low=True)
    lim.record(4, low=True)
    assert lim.delay_ms(5, low=True) > 0      # pay doldu
    assert lim.delay_ms(5, low=False) == 10_000 - 5  # pencere (5) doldu: canlı da en eski isteği bekler


def simulate_backfill_rate(n_symbols: int, hours: int = 2) -> float:
    """Varsayılanlarla: her 5m mum + 30 sn'de 5*n canlı istek (yüksek öncelik, bitene kadar
    doldurma bekler), arada doldurma sınırlayıcının izin verdiği kadar. Döner: 5 dk'da doldurma isteği."""
    from cyberbot.recorder.binance_rest import BinanceRest
    from cyberbot.recorder.defaults import RECORDER_DEFAULTS

    b = RECORDER_DEFAULTS["binance"]
    lim = make(max_rps=b["max_rps"], window_s=b["window_s"], window_max=b["window_max"])
    holder = type("H", (), {"limiter": lim})()
    BinanceRest.set_low_cap(holder, n_symbols)  # gerçek formül
    pending = low_sent = 0
    bar = 300_000
    for t in range(0, hours * 3_600_000, 50):
        if t % bar == 30_000:
            pending += 5 * n_symbols
        if pending:
            if lim.delay_ms(t) <= 0:
                lim.record(t)
                pending -= 1
            continue
        if lim.delay_ms(t, low=True) <= 0:
            lim.record(t, low=True)
            low_sent += 1
    assert pending == 0 or pending <= 5 * n_symbols  # canlı tur her zaman yetişir
    return low_sent / (hours * 12)


def test_backfill_keeps_its_reserved_share_with_60_symbols():
    # 60 Binance sembolü: canlı 300 istek/5 dk; low_cap = 700 - 400 = 300. Eskiden ~1 istek/5 dk kalıyordu.
    rate = simulate_backfill_rate(60)
    assert rate >= 250
    assert simulate_backfill_rate(65) >= 200
    # 29.5 günlük ilk doldurma (60 sembol x 5 uç x 16 istek) birkaç saatte biter
    assert 60 * 5 * 16 / rate * 5 / 60 < 6


def test_pause_blocks_everything_and_retry_after_parsing():
    lim = make()
    lim.pause(30, now=1000, reason="HTTP 429")
    assert lim.paused(20_000) and lim.delay_ms(20_000) == 11_000
    assert not lim.paused(31_000)
    lim.pause(5, now=2000)  # daha kısa duraklatma uzatmaz/kısaltmaz
    assert lim.paused_until_ms == 31_000
    assert retry_after_s({"retry-after": "120"}, 60) == 120
    assert retry_after_s({}, 60) == 60
    assert retry_after_s({"retry-after": "abc"}, 7) == 7


def test_acquire_waits_with_clock_and_rps_holds():
    clock = FakeClock(0)
    lim = make(max_rps=2.0, clock=clock)

    async def main():
        for _ in range(5):
            await lim.acquire()
        return list(lim.stamps)

    stamps = asyncio.run(main())
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 500 for g in gaps)


def test_window_never_exceeded_over_long_run():
    clock = FakeClock(0)
    lim = make(max_rps=100, window_s=300, window_max=700, clock=clock)

    async def main():
        for _ in range(2000):
            await lim.acquire(low=True)

    asyncio.run(main())
    stamps = list(lim.stamps)
    # her 300 sn'lik kayan pencerede en fazla 700
    j = 0
    for i, t in enumerate(stamps):
        while stamps[j] <= t - 300_000:
            j += 1
        assert i - j + 1 <= 700


def test_high_priority_goes_first():
    clock = FakeClock(0)
    lim = make(max_rps=2.0, clock=clock)
    order = []

    async def low():
        for i in range(3):
            await lim.acquire(low=True)
            order.append(f"low{i}")

    async def high():
        with lim.high_section():
            for i in range(3):
                await lim.acquire()
                order.append(f"high{i}")
                await asyncio.sleep(0)

    async def main():
        await asyncio.gather(high(), low())

    asyncio.run(main())
    assert order[:3] == ["high0", "high1", "high2"]
