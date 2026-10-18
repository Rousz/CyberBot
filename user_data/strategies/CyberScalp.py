"""CyberScalp: WEEX USDT-M vadeli scalp stratejisi (Faz 1, Freqtrade 2026.9).

İnce Freqtrade katmanı; asıl mantık cyberbot.strategy.* (saf, test edilebilir):
- Trend filtresi + trend puanı + geri çekilme tetiği (kapanmış 5m mum), stop/hedef, R/R >= min_rr
- Aynı mumda birden çok sinyal -> en yüksek puan önce (confirm_trade_entry)
- Dry-run/canlı: emir defteri derinlik kontrolü, borsa sağlık kilidi + Telegram, uptime kaydı

Ayarlar: config.json -> "cyberbot": {"strategy": {...}} (varsayılanlar cyberbot/strategy/defaults.py).
Yan etkiler (Telegram, DB yazma, ağ) sadece dp.runmode DRY_RUN/LIVE iken.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pandas import DataFrame

from freqtrade import __version__ as ft_version
from freqtrade.enums import RunMode
from freqtrade.exchange import timeframe_to_minutes, timeframe_to_prev_date, timeframe_to_seconds
from freqtrade.persistence import Order, Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_absolute

from cyberbot import __version__ as cyberbot_version
from cyberbot import notify, paths, timeutil, uptime
from cyberbot.strategy import core, defaults, health, ranking

logger = logging.getLogger(__name__)

LIVE_MODES = (RunMode.DRY_RUN, RunMode.LIVE)
LOCK_REASON = "exchange_down"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class CyberScalp(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    minimal_roi = {"0": 100}  # hedef custom_exit'te; ROI pratikte kapalı
    stoploss = -0.30  # sert tavan (3x'te %10 fiyat); asıl stop custom_stoploss
    use_custom_stoploss = True
    use_exit_signal = True  # custom_exit için gerekli; çıkış sinyali üretilmez
    exit_profit_only = False
    process_only_new_candles = True
    startup_candle_count = 400

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.p = defaults.load(config)
        stake = config.get("stake_currency", "USDT")
        self.btc_pair = f"BTC/{stake}:{stake}"
        self.btc_prefix = f"btc_{stake.lower()}_"
        self._signals: dict[str, dict[int, dict]] = {}
        self._binance = self._make_binance()
        self._health: health.ExchangeHealth | None = None
        self._depth_logged: dict[str, int] = {}
        self._uptime_store: uptime.UptimeStore | None = None
        self._uptime_session: int | None = None
        self._heartbeat: uptime.Heartbeat | None = None

    # ------------------------------------------------------------------ yardımcılar

    def _is_live(self) -> bool:
        return self.dp is not None and self.dp.runmode in LIVE_MODES

    def _make_binance(self) -> ranking.BinancePerps:
        r = self.p["ranking"]
        return ranking.BinancePerps(paths.binance_perps_json, refresh_s=float(r["binance_refresh_s"]),
                                    max_age_hours=float(r["binance_max_age_hours"]))

    def _signal_ms(self, when: datetime) -> int:
        """Bu ana ait sinyal mumu: son kapanmış mum (backtest'te giriş mumundan bir önceki)."""
        tf = timedelta(minutes=timeframe_to_minutes(self.timeframe))
        return _ms(timeframe_to_prev_date(self.timeframe, when) - tf)

    def _signal(self, pair: str, when: datetime) -> dict | None:
        return self._signals.get(pair, {}).get(self._signal_ms(when))

    # ------------------------------------------------------------------ yaşam döngüsü

    def bot_start(self, **kwargs) -> None:
        self.p = defaults.load(self.config)
        errors = defaults.validate(self.p)
        if errors:
            raise ValueError("CyberScalp ayar hatası (config.json cyberbot.strategy): " + "; ".join(errors))
        used, missing = core.enabled_layers(self.p)
        if missing:
            logger.warning("CyberScalp: açık ama henüz yazılmamış puan katmanları yok sayılıyor: %s",
                           ", ".join(missing))
        if not used:
            logger.warning("CyberScalp: hiçbir puan katmanı açık değil; giriş sinyali oluşmaz.")
        self._signals = {}
        self._binance = self._make_binance()
        h = self.p["health"]
        self._health = health.ExchangeHealth(
            timeframe_s=timeframe_to_seconds(self.timeframe),
            max_candle_delay_s=float(h["max_candle_delay_s"]),
            lock_minutes=float(h["lock_minutes"]),
            recovery_loops=int(h["recovery_loops"]),
        )
        if self._is_live():
            self._start_uptime()

    def _start_uptime(self) -> None:
        try:
            self._stop_uptime("reload")  # bot_start tekrar çağrıldıysa önceki oturumu kapat
            self._uptime_store = uptime.UptimeStore(paths.uptime_db(), "freqtrade")
            self._uptime_session = self._uptime_store.start_session(
                version=f"cyberbot {cyberbot_version} / freqtrade {ft_version}",
                detail=f"strategy=CyberScalp runmode={self.dp.runmode.value}",
            )
            self._heartbeat = uptime.Heartbeat(self._uptime_store, self._uptime_session).start()
        except Exception as exc:  # uptime kaydı botu asla durdurmaz
            logger.warning("Uptime kaydı başlatılamadı: %s", exc)

    def _stop_uptime(self, kind: str) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        if self._uptime_store is not None and self._uptime_session is not None:
            self._uptime_store.stop_session(self._uptime_session, kind=kind)
        self._uptime_session = None

    def _uptime_event(self, kind: str, detail: str) -> None:
        try:
            store = self._uptime_store or uptime.UptimeStore(paths.uptime_db(), "freqtrade")
            store.add_event(kind, detail)
        except Exception as exc:
            logger.warning("Uptime olayı yazılamadı (%s): %s", kind, exc)

    def ft_bot_cleanup(self) -> None:
        try:
            super().ft_bot_cleanup()
        finally:
            try:
                self._stop_uptime("clean")
            except Exception as exc:  # kapanış asla bozulmaz
                logger.warning("Uptime kapanış kaydı yazılamadı: %s", exc)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if not self._is_live() or self._health is None or not self.p["health"]["enabled"]:
            return
        df = self.dp.ohlcv(self.btc_pair, self.timeframe, copy=False)
        last_ms = _ms(df["date"].iloc[-1].to_pydatetime()) if df is not None and len(df) else None
        now_ms = _ms(current_time)
        d = self._health.update(last_ms, now_ms)
        if d.lock_until_ms is not None:
            self.lock_pair("*", until=timeutil.from_ms(d.lock_until_ms), reason=LOCK_REASON)
        if d.transition == "down":
            last_txt = timeutil.fmt_both(timeutil.from_ms(last_ms)) if last_ms else "yok"
            logger.warning("WEEX verisi bayat (%s 5m son mum: %s); yeni işlemler kilitlendi.",
                           self.btc_pair, last_txt)
            self.dp.send_msg(
                "*CyberBot uyarı:* WEEX verisi gecikiyor, yeni işlem açılmıyor.\n"
                f"{notify.md_escape(self.btc_pair)} 5m son mum: {notify.md_escape(last_txt)}\n"
                "Açık işlemler kapatılmaz; stop/hedef takibi veri geldikçe sürer.",
                always_send=True,
            )
            self._uptime_event("exchange_down", f"{self.btc_pair} 5m son mum {last_txt}")
        elif d.transition == "recovered":
            self.unlock_reason(LOCK_REASON)
            when_txt = timeutil.fmt_both(current_time)
            logger.info("WEEX verisi düzeldi; işlem kilidi kaldırıldı.")
            self.dp.send_msg(
                "*CyberBot:* WEEX verisi düzeldi, yeni işlemlere tekrar izin verildi.\n"
                f"Zaman: {notify.md_escape(when_txt)}",
                always_send=True,
            )
            self._uptime_event("exchange_recovered", when_txt)

    # ------------------------------------------------------------------ veri

    def informative_pairs(self):
        # sağlık kontrolü için BTC 5m her zaman güncellensin (whitelist'te olmasa da)
        return [(self.btc_pair, self.timeframe)]

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return core.add_informative(dataframe, self.p)

    @informative("1h", "BTC/{stake}:{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return core.add_informative(dataframe, self.p)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return core.add_indicators(dataframe, self.p)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = core.populate_signals(dataframe, self.p, self.btc_prefix, self.timeframe)
        # sıralama ve emir planı için sinyal satırlarını sakla (backtest: tüm geçmiş, canlı: son pencere)
        self._signals[metadata["pair"]] = core.signal_rows(dataframe)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    # ------------------------------------------------------------------ giriş

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return float(min(float(self.p["leverage"]), max_leverage))

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        sig = self._signal(pair, current_time)
        if sig is None:
            logger.info("%s: sinyal satırı bulunamadı, işlem atlandı.", pair)
            return 0.0
        equity = self.wallets.get_total_stake_amount() if self.wallets else proposed_stake
        return core.risk_stake(
            equity=equity, risk_per_trade=float(self.p["risk_per_trade"]), rate=current_rate, sl=sig["sl"],
            leverage=leverage, min_stake=min_stake, max_stake=max_stake, proposed_stake=proposed_stake,
            cap_to_slot=bool(self.p["cap_stake_to_slot"]),
        )

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None, side: str,
                            **kwargs) -> bool:
        live = self._is_live()
        if live and self._health is not None and not self._health.healthy:
            return False
        if not self._ranked_first(pair, current_time):
            return False
        if live and self.p["depth"]["enabled"]:
            return self._depth_ok(pair, side, current_time)
        return True

    def _ranked_first(self, pair: str, current_time: datetime) -> bool:
        signal_ms = self._signal_ms(current_time)
        open_pairs = {t.pair for t in Trade.get_trades_proxy(is_open=True)}
        candidates: dict[str, float] = {}
        whitelist = self.dp.current_whitelist() if self.dp else [pair]
        for p in set(whitelist) | {pair}:
            sig = self._signals.get(p, {}).get(signal_ms)
            # kilit, Freqtrade'in kendi giriş kontrolü gibi mum zamanına göre (backtest'te de doğru)
            if sig is None or p in open_pairs or (p != pair and self.is_pair_locked(p, candle_date=current_time)):
                continue
            candidates[p] = sig["score"]
        max_open = self.config.get("max_open_trades", 1)
        free = (float("inf") if max_open in (-1, None) else float(max_open)) - Trade.get_open_trade_count()
        bonus = float(self.p["ranking"]["binance_priority_bonus"])
        bonus_pairs = self._binance.pairs() if bonus else frozenset()
        ok = ranking.is_selected(pair, candidates, free, bonus_pairs, bonus)
        if not ok:
            logger.debug("%s: aynı mumda daha yüksek puanlı sinyaller var, atlandı.", pair)
        return ok

    def _depth_ok(self, pair: str, side: str, current_time: datetime) -> bool:
        d = self.p["depth"]
        try:
            book = self.dp.orderbook(pair, int(d["levels"]))
            ok, notional = core.depth_ok(book, side, float(d["band_pct"]), float(d["min_depth_usdt"]))
        except Exception as exc:
            ok, notional = False, 0.0
            logger.warning("%s: emir defteri alınamadı (%s), giriş reddedildi.", pair, exc)
        if not ok:
            signal_ms = self._signal_ms(current_time)
            if self._depth_logged.get(pair) != signal_ms:  # mum başına bir log satırı
                self._depth_logged[pair] = signal_ms
                logger.info("%s: derinlik yetersiz (+/-%%%.2f içinde %.0f USDT < %.0f), giriş reddedildi.",
                            pair, float(d["band_pct"]) * 100, notional, float(d["min_depth_usdt"]))
        return ok

    # ------------------------------------------------------------------ işlem yönetimi

    def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs) -> None:
        if order.ft_order_side != trade.entry_side or trade.get_custom_data("sl") is not None:
            return
        sig = self._signal(pair, trade.open_date_utc)
        if sig is None:
            logger.warning("%s: sinyal satırı bulunamadı; stop max_stop_pct ile kuruldu.", pair)
        plan = core.plan_from_fill(
            float(trade.open_rate), sig["sl"] if sig else None, bool(trade.is_short),
            float(self.p["target_rr"]), float(self.p["stop"]["max_stop_pct"]),
        )
        trade.set_custom_data("sl", plan["sl"])
        trade.set_custom_data("tp", plan["tp"])
        trade.set_custom_data("rr", plan["rr"])
        trade.set_custom_data("risk_pct", plan["risk_pct"])
        if sig is not None:
            trade.set_custom_data("score", sig["score"])
        trade.set_custom_data("plan_source", plan["source"])
        if plan["crossed"]:
            trade.set_custom_data("fill_beyond_stop", True)
            logger.warning("%s: dolum fiyatı stopu geçmiş (%.8g / stop %.8g); hemen çıkılacak.",
                           pair, trade.open_rate, plan["sl"])

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        sl = trade.get_custom_data("sl")
        if sl is None:
            return None
        return stoploss_from_absolute(float(sl), current_rate, is_short=trade.is_short, leverage=trade.leverage)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs) -> str | None:
        tp = trade.get_custom_data("tp")
        held = (current_time - trade.open_date_utc).total_seconds() / 60
        return core.exit_reason(
            is_short=bool(trade.is_short), rate=current_rate, tp=float(tp) if tp is not None else None,
            crossed=bool(trade.get_custom_data("fill_beyond_stop", False)), held_minutes=held,
            max_hold_minutes=float(self.p["max_hold_minutes"]),
        )
