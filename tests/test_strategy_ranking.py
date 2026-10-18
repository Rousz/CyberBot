"""Sinyal önceliği: en yüksek puan önce, boş slot sayısı kadar; Binance bonusu; derinlik kontrolü."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cyberbot import paths
from cyberbot.strategy import ranking
from freqtrade.enums import RunMode
from freqtrade.persistence import LocalTrade, Trade
from tests.test_strategy_health import FakeDP, strategy  # noqa: F401  (fixture)

HOUR_MS = 3_600_000
NOW = 1_768_003_200_000  # 2026-01-10 00:00 UTC


# --------------------------------------------------------------------------- saf sıralama


def test_rank_by_score_then_pair_name():
    cands = {"SOL/USDT:USDT": 75.0, "ETH/USDT:USDT": 80.0, "ADA/USDT:USDT": 75.0}
    assert ranking.rank(cands) == ["ETH/USDT:USDT", "ADA/USDT:USDT", "SOL/USDT:USDT"]


def test_is_selected_respects_free_slots():
    cands = {"A": 90.0, "B": 80.0, "C": 70.0}
    assert ranking.is_selected("A", cands, 1) and not ranking.is_selected("B", cands, 1)
    assert ranking.is_selected("B", cands, 2) and not ranking.is_selected("C", cands, 2)
    assert not ranking.is_selected("A", cands, 0)
    assert ranking.is_selected("C", cands, float("inf"))
    assert ranking.is_selected("X", cands, 1)  # sıralama bilgisi yoksa engellemez


def test_binance_bonus_only_reorders():
    cands = {"A": 80.0, "B": 77.0}
    assert ranking.rank(cands, {"B"}, 5.0) == ["B", "A"]
    assert ranking.rank(cands, {"B"}, 2.0) == ["A", "B"]


def write_perps(path, generated_ms, pairs=("SOL/USDT:USDT",)):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_ms": generated_ms, "pairs": {
        p: {"binance_symbol": p.split("/")[0] + "USDT", "multiplier": 1.0, "method": "exact"} for p in pairs}}),
        encoding="utf-8")


def test_binance_perps_cache_age_and_refresh(tmp_path):
    path = tmp_path / "binance_perps.json"
    clock = {"now": NOW}
    perps = ranking.BinancePerps(lambda: path, refresh_s=3600, max_age_hours=48, clock_ms=lambda: clock["now"])
    assert perps.pairs() == frozenset()  # dosya yok
    write_perps(path, NOW)
    assert perps.pairs() == frozenset()  # en fazla saatte bir okunur
    clock["now"] += HOUR_MS
    assert perps.pairs() == {"SOL/USDT:USDT"}
    write_perps(path, NOW, ("ETH/USDT:USDT",))
    clock["now"] += 10 * 60_000
    assert perps.pairs() == {"SOL/USDT:USDT"}  # önbellekten
    clock["now"] = NOW + 49 * HOUR_MS  # 48 saatten eski -> bonus yok (yeniden okunsa da eski)
    assert perps.pairs() == frozenset()


def test_binance_perps_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "binance_perps.json"
    path.write_text("{bozuk", encoding="utf-8")
    assert ranking.BinancePerps(lambda: path, clock_ms=lambda: NOW).pairs() == frozenset()


# --------------------------------------------------------------------------- strateji: confirm_trade_entry


def at(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@pytest.fixture
def ranked(strategy):  # noqa: F811
    Trade.use_db = False
    LocalTrade.reset_trades()
    strategy.dp.runmode = RunMode.BACKTEST  # derinlik/sağlık kontrolü yok, sadece sıralama
    strategy.bot_start()
    signal_ms = NOW
    strategy.dp.whitelist = ["ETH/USDT:USDT", "SOL/USDT:USDT", "BTC/USDT:USDT"]
    strategy._signals = {
        "ETH/USDT:USDT": {signal_ms: {"side": "long", "score": 80.0, "sl": 99.0, "tp": 101.8, "rr": 1.8}},
        "SOL/USDT:USDT": {signal_ms: {"side": "long", "score": 78.0, "sl": 99.0, "tp": 101.8, "rr": 1.8}},
        "BTC/USDT:USDT": {signal_ms: {"side": "short", "score": 72.0, "sl": 101, "tp": 98.2, "rr": 1.8},
                          signal_ms - 300_000: {"side": "long", "score": 99.0, "sl": 99, "tp": 101.8, "rr": 1.8}},
    }
    yield strategy
    LocalTrade.reset_trades()


def confirm(strat, pair, when_ms=NOW + 300_000, side="long"):
    # backtest: giriş mumunun açılışı (sinyal mumu + 5m)
    return strat.confirm_trade_entry(pair, "market", 1.0, 100.0, "GTC", at(when_ms), None, side)


def test_confirm_accepts_only_top_scores_for_free_slots(ranked):
    ranked.config["max_open_trades"] = 1
    assert confirm(ranked, "ETH/USDT:USDT")
    assert not confirm(ranked, "SOL/USDT:USDT") and not confirm(ranked, "BTC/USDT:USDT", side="short")
    ranked.config["max_open_trades"] = 2
    assert confirm(ranked, "SOL/USDT:USDT") and not confirm(ranked, "BTC/USDT:USDT", side="short")
    ranked.config["max_open_trades"] = 3
    assert confirm(ranked, "BTC/USDT:USDT", side="short")


def test_confirm_uses_signal_candle_in_live_time_too(ranked):
    ranked.config["max_open_trades"] = 1
    # canlı: 00:05:03'te son kapanmış mum 00:00 (sinyal) -> aynı sıralama
    assert confirm(ranked, "ETH/USDT:USDT", when_ms=NOW + 303_000)
    assert not confirm(ranked, "SOL/USDT:USDT", when_ms=NOW + 303_000)


def test_binance_bonus_changes_priority(ranked):
    write_perps(paths.binance_perps_json(), int(datetime.now(timezone.utc).timestamp() * 1000))
    ranked._binance = ranked._make_binance()  # önbellek yeniden kurulur
    ranked.dp.runmode = RunMode.DRY_RUN
    ranked.config["max_open_trades"] = 1
    assert confirm(ranked, "SOL/USDT:USDT")  # 78 + 5 > 80
    assert not confirm(ranked, "ETH/USDT:USDT")


def test_binance_bonus_not_applied_in_backtest(ranked):
    # bugünkü liste geçmişe uygulanmaz: aynı backtest dosyanın yaşına/varlığına bağlı değil
    write_perps(paths.binance_perps_json(), int(datetime.now(timezone.utc).timestamp() * 1000))
    ranked._binance = ranked._make_binance()
    ranked.config["max_open_trades"] = 1
    assert confirm(ranked, "ETH/USDT:USDT") and not confirm(ranked, "SOL/USDT:USDT")


# --------------------------------------------------------------------------- girilemeyen pariteler sıralamada yok


def test_side_specific_auto_lock_frees_slot_for_next_pair(ranked):
    ranked.config["max_open_trades"] = 1
    # ETH'nin işlemi giriş mumunun başında kapandı -> Freqtrade "Auto lock" (yöne özel, mum sonuna kadar)
    ranked.lock_pair("ETH/USDT:USDT", at(NOW + 302_000), reason="Auto lock", side="long")
    assert ranked.is_pair_locked("ETH/USDT:USDT", candle_date=at(NOW), side="long")  # Freqtrade ETH'yi engeller
    assert confirm(ranked, "SOL/USDT:USDT")  # ...o yüzden ETH sıralamada yer tutmaz


def test_opposite_side_lock_does_not_remove_candidate(ranked):
    ranked.config["max_open_trades"] = 1
    ranked.lock_pair("ETH/USDT:USDT", at(NOW + 302_000), reason="Auto lock", side="short")
    assert not confirm(ranked, "SOL/USDT:USDT")  # ETH long girebilir, hâlâ önde


def exit_fill(strat, pair, when_ms, direction="long"):
    trade = SimpleNamespace(exit_side="sell" if direction == "long" else "buy",
                            entry_side="buy" if direction == "long" else "sell", trade_direction=direction)
    strat.order_filled(pair, trade, SimpleNamespace(ft_order_side=trade.exit_side), at(when_ms))


def test_pair_closed_in_this_candle_is_not_a_candidate_in_backtest(ranked):
    ranked.config["max_open_trades"] = 1
    exit_fill(ranked, "ETH/USDT:USDT", NOW - 300_000)  # sinyal mumundan önce kapandı: girebilir
    assert not confirm(ranked, "SOL/USDT:USDT")
    # backtest: ETH'nin işlemi giriş mumunda kapandı -> Freqtrade ETH'yi bu mum atlar
    exit_fill(ranked, "ETH/USDT:USDT", NOW + 300_000, direction="short")
    assert confirm(ranked, "SOL/USDT:USDT")


def test_pair_closed_in_this_candle_live_only_same_side_blocks(ranked):
    ranked.dp.runmode = RunMode.DRY_RUN
    ranked.config["max_open_trades"] = 1
    exit_fill(ranked, "ETH/USDT:USDT", NOW + 302_000, direction="short")  # ters yön: Freqtrade izin verir
    assert not confirm(ranked, "SOL/USDT:USDT", when_ms=NOW + 303_000)
    exit_fill(ranked, "ETH/USDT:USDT", NOW + 302_000, direction="long")
    assert confirm(ranked, "SOL/USDT:USDT", when_ms=NOW + 303_000)


def test_thin_book_top_pair_does_not_block_liquid_lower_pair(ranked):
    ranked.dp.runmode = RunMode.DRY_RUN
    ranked.config["max_open_trades"] = 1
    books = {"ETH/USDT:USDT": {"bids": [[100.0, 1]], "asks": [[100.1, 1]]},  # ~100 USDT
             "SOL/USDT:USDT": {"bids": [[100.0, 10_000]], "asks": [[100.1, 10_000]]}}
    ranked.dp.orderbook = lambda pair, maximum: books[pair]
    when = NOW + 303_000
    assert not confirm(ranked, "SOL/USDT:USDT", when_ms=when)  # ETH henüz denenmedi: önde
    assert not confirm(ranked, "ETH/USDT:USDT", when_ms=when)  # derinlik yetersiz
    assert confirm(ranked, "SOL/USDT:USDT", when_ms=when + 5_000)  # sonraki döngü: SOL girer
    # sonraki mumda ETH yeniden aday (kayıt sadece o sinyal mumu için)
    nxt = NOW + 300_000
    for p in ("ETH/USDT:USDT", "SOL/USDT:USDT"):
        ranked._signals[p][nxt] = dict(ranked._signals[p][NOW])
    assert not confirm(ranked, "SOL/USDT:USDT", when_ms=nxt + 303_000)
    assert not confirm(ranked, "ETH/USDT:USDT", when_ms=nxt + 303_000)
    assert set(ranked._rejected) == {nxt}  # eski mum kayıtları silinir


def test_zero_stake_top_pair_does_not_block_next_pair(ranked):
    ranked.config["max_open_trades"] = 1
    # slot payı (5 USDT) borsa alt sınırının (10 USDT) altında -> Freqtrade ETH'yi açmaz
    stake = ranked.custom_stake_amount("ETH/USDT:USDT", at(NOW + 300_000), 100.0, 5.0, 10.0, 100.0, 3.0,
                                       None, "long")
    assert stake == 0
    assert confirm(ranked, "SOL/USDT:USDT")


def test_depth_check_only_in_dry_run(ranked):
    ranked.config["max_open_trades"] = 3
    ranked.dp.book = {"bids": [[100.0, 1]], "asks": [[100.1, 1]]}  # ~100 USDT derinlik
    assert confirm(ranked, "ETH/USDT:USDT")  # backtest: derinlik kontrolü yok
    ranked.dp.runmode = RunMode.DRY_RUN
    assert not confirm(ranked, "ETH/USDT:USDT")
    ranked.dp.book = {"bids": [[100.0, 1000]], "asks": [[100.1, 1000]]}  # ~100k USDT
    assert confirm(ranked, "ETH/USDT:USDT")
