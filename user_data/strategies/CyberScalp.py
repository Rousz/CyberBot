"""CyberScalp: WEEX USDT-M vadeli scalp stratejisi (Faz 1, Freqtrade 2026.9).

İnce Freqtrade katmanı; asıl mantık cyberbot.strategy.* (saf, test edilebilir):
- Trend filtresi + trend puanı + geri çekilme tetiği (kapanmış 5m mum), stop/hedef, brüt R/R >= min_rr
- Aynı mumda birden çok sinyal -> en yüksek puan önce (confirm_trade_entry)
- Dry-run/canlı: emir defteri derinlik kontrolü, borsa sağlık kilidi + Telegram, uptime kaydı

Çıkışlar: stop = custom_stoploss ("stop_loss"), hedef = custom_roi ("roi"; backtest'te mum
tepe/dibiyle mum içinde), süre dolumu / stopu geçmiş dolum = custom_exit ("time_stop",
"fill_beyond_stop").

Ayarlar: config.json -> "cyberbot": {"strategy": {...}} (varsayılanlar cyberbot/strategy/defaults.py).
Yan etkiler (Telegram, DB yazma, ağ) sadece dp.runmode DRY_RUN/LIVE iken.
"""

from __future__ import annotations

import logging
import sys
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
# Kalp atışı sadece ana döngü ilerliyorsa yazılır (bot_loop_start son ALIVE_INTERVALS kalp
# atışı aralığı içinde çalıştıysa). İlk döngü başlangıç verisini indirir: STARTUP_GRACE_S pay.
HEARTBEAT_STARTUP_GRACE_S = 15 * 60
HEARTBEAT_ALIVE_INTERVALS = 3


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class CyberScalp(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = True
    minimal_roi = {"0": 100}  # ROI tablosu pratikte kapalı; hedef (tp) custom_roi ile
    use_custom_roi = True
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
        # sinyal mumu -> derinlik/teminat yüzünden giremeyen pariteler (sıralamada atlanır)
        self._rejected: dict[int, set[str]] = {}
        # parite -> (son çıkış dolumu UTC ms, yön): bu mumda kapanan parite tekrar giremez
        self._exits: dict[str, tuple[int, str]] = {}
        self._uptime_store: uptime.UptimeStore | None = None
        self._uptime_session: int | None = None  # ilk oturum; güncel olan self._heartbeat.session_id
        self._heartbeat: uptime.Heartbeat | None = None
        self._heartbeat_interval_s = float(uptime.HEARTBEAT_INTERVAL_S)
        self._uptime_started_ms: int | None = None
        self._last_loop_ms: int | None = None

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

    def _reject(self, pair: str, when: datetime) -> bool:
        """Bu sinyal mumunda pair'in giremediğini kaydet (sıralamada alttakilere yer açılır).
        True = bu mum için ilk kayıt (log bir kez yazılsın)."""
        signal_ms = self._signal_ms(when)
        for old in [k for k in self._rejected if k < signal_ms]:
            del self._rejected[old]
        pairs = self._rejected.setdefault(signal_ms, set())
        if pair in pairs:
            return False
        pairs.add(pair)
        return True

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
        self._rejected, self._exits = {}, {}
        self._binance = self._make_binance()
        if not self._is_live() and float(self.p["ranking"]["binance_priority_bonus"]):
            # bugünkü Binance listesi geçmişe uygulanmaz; aynı backtest her zaman aynı sonucu verir
            logger.info("CyberScalp: backtest/analizde Binance öncelik bonusu uygulanmıyor.")
        h = self.p["health"]
        self._health = health.ExchangeHealth(
            timeframe_s=timeframe_to_seconds(self.timeframe),
            max_candle_delay_s=float(h["max_candle_delay_s"]),
            lock_minutes=float(h["lock_minutes"]),
            recovery_loops=int(h["recovery_loops"]),
        )
        if self._is_live():
            self._start_uptime()
            self._reset_health_lock()

    def _reset_health_lock(self) -> None:
        """Yeniden başlatmada önceki süreçten kalan "exchange_down" kilidini kaldırır.

        Kilit Freqtrade veritabanında kalır ama yeni sağlık makinesi sağlıklı başlar; "düzeldi"
        geçişi hiç olmayacağı için kilit sessizce ~15 dk işlemi durdururdu. Veri hâlâ bayatsa
        ilk bot_loop_start kilidi ve uyarıyı yeniden koyar. Son sağlık olayı exchange_down ise
        olay çifti kapansın diye exchange_recovered (başlangıçta sıfırlandı) yazılır."""
        try:
            self.unlock_reason(LOCK_REASON)
        except Exception as exc:
            logger.warning("Önceki borsa kilidi kaldırılamadı: %s", exc)
        try:
            store = self._uptime_store or uptime.UptimeStore(paths.uptime_db(), "freqtrade")
            kinds = [e.kind for e in store.events() if e.kind in ("exchange_down", "exchange_recovered")]
            if kinds and kinds[-1] == "exchange_down":
                logger.info("Önceki çalışmadan kalan WEEX kesinti kaydı başlangıçta kapatıldı.")
                store.add_event("exchange_recovered", "yeniden başlatmada sıfırlandı")
        except Exception as exc:
            logger.warning("Uptime olayı yazılamadı (exchange_recovered): %s", exc)

    def _start_uptime(self) -> None:
        try:
            self._stop_uptime("reload")  # bot_start tekrar çağrıldıysa önceki oturumu kapat
            self._uptime_store = uptime.UptimeStore(paths.uptime_db(), "freqtrade")
            version = f"cyberbot {cyberbot_version} / freqtrade {ft_version}"
            self._uptime_session = self._uptime_store.start_session(
                version=version, detail=f"strategy=CyberScalp runmode={self.dp.runmode.value}",
            )
            self._uptime_started_ms = uptime.now_ms()
            self._last_loop_ms = None
            self._heartbeat = uptime.Heartbeat(
                self._uptime_store, self._uptime_session, self._heartbeat_interval_s,
                is_alive=self._loop_alive, version=version,
            ).start()
        except Exception as exc:  # uptime kaydı botu asla durdurmaz
            logger.warning("Uptime kaydı başlatılamadı: %s", exc)

    def _loop_alive(self) -> bool:
        """Freqtrade ana döngüsü ilerliyor mu? (kalp atışı iş parçacığı sorar)

        Bot STOPPED durumuna düşerse (ör. OperationalException) veya döngü takılırsa
        bot_loop_start çağrılmaz; kalp atışı kesilir, izleme uyarır, rapor kesinti sayar."""
        now = uptime.now_ms()
        if self._last_loop_ms is None:
            started = self._uptime_started_ms if self._uptime_started_ms is not None else now
            return now - started <= HEARTBEAT_STARTUP_GRACE_S * 1000
        return now - self._last_loop_ms <= HEARTBEAT_ALIVE_INTERVALS * self._heartbeat_interval_s * 1000

    def _stop_uptime(self, kind: str) -> None:
        hb, self._heartbeat = self._heartbeat, None
        session = self._uptime_session
        at_ms = None
        if hb is not None:
            hb.stop()
            session = hb.session_id  # takılma sonrası yeni oturum açılmış olabilir
            if hb.stalled and self._uptime_store is not None:
                # ana döngü zaten durmuştu: oturum son kalp atışında biter (duruş çalışma sayılmaz)
                if kind in uptime.NORMAL_STOP_KINDS:
                    kind = "stalled"
                last = next((s.last_heartbeat_ms for s in self._uptime_store.sessions() if s.id == session), None)
                if last is not None:
                    at_ms = min(uptime.now_ms(), last + int(hb.interval_s * 1000))
        if self._uptime_store is not None and session is not None:
            self._uptime_store.stop_session(session, kind=kind, at_ms=at_ms)
        self._uptime_session = None

    def _uptime_event(self, kind: str, detail: str) -> None:
        try:
            store = self._uptime_store or uptime.UptimeStore(paths.uptime_db(), "freqtrade")
            store.add_event(kind, detail)
        except Exception as exc:
            logger.warning("Uptime olayı yazılamadı (%s): %s", kind, exc)

    @staticmethod
    def _stop_kind(exc: BaseException | None) -> str:
        """Kapanış türü: düzenli çıkış (docker stop/Ctrl-C = KeyboardInterrupt, SystemExit,
        istisnasız) "clean"; Freqtrade'i düşüren istisna "crash:<İstisnaAdı>"."""
        if exc is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return "clean"
        return f"crash:{type(exc).__name__}"

    def ft_bot_cleanup(self) -> None:
        # start_trading'in finally bloğundan çağrılır: yayılan istisna burada sys.exc_info()'da
        kind = self._stop_kind(sys.exc_info()[1])
        try:
            super().ft_bot_cleanup()
        finally:
            try:
                self._stop_uptime(kind)
            except Exception as exc:  # kapanış asla bozulmaz
                logger.warning("Uptime kapanış kaydı yazılamadı: %s", exc)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        self._last_loop_ms = uptime.now_ms()  # kalp atışı: ana döngü ilerliyor
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
        stake = core.risk_stake(
            equity=equity, risk_per_trade=float(self.p["risk_per_trade"]), rate=current_rate, sl=sig["sl"],
            leverage=leverage, min_stake=min_stake, max_stake=max_stake, proposed_stake=proposed_stake,
            cap_to_slot=bool(self.p["cap_stake_to_slot"]), round_trip_fee=float(self.p["round_trip_fee"]),
        )
        if stake <= 0 and self._reject(pair, current_time):
            logger.info("%s: risk tabanlı teminat borsa alt sınırına (%s) uymuyor, işlem atlandı.",
                        pair, min_stake)
        return stake

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

    def _cannot_enter(self, p: str, side: str, signal_ms: int, live: bool) -> bool:
        """Freqtrade bu sinyal mumunda p'ye girmez mi? (sıralamada aday sayılmaz)"""
        if p in self._rejected.get(signal_ms, ()):  # derinlik yetersiz / teminat 0
            return True
        # Freqtrade'in kendi kontrolüyle aynı: sinyal mumu tarihi + sinyal yönü (yöne özel
        # "Auto lock" dahil); backtest de giriş mumu açılışında aynı kilidi denetler
        if self.is_pair_locked(p, candle_date=timeutil.from_ms(signal_ms), side=side):
            return True
        # bu mumda (sinyal mumu kapandıktan sonra) kapanan işlem: backtest o pariteyi bu mum
        # atlar; canlıda aynı yön bir mum kilitlenir (kilit DB'den gelmese de)
        tf_ms = timeframe_to_seconds(self.timeframe) * 1000
        exit_ = self._exits.get(p)
        return exit_ is not None and exit_[0] >= signal_ms + tf_ms and (not live or exit_[1] == side)

    def _ranked_first(self, pair: str, current_time: datetime) -> bool:
        signal_ms = self._signal_ms(current_time)
        live = self._is_live()
        open_pairs = {t.pair for t in Trade.get_trades_proxy(is_open=True)}
        candidates: dict[str, float] = {}
        whitelist = self.dp.current_whitelist() if self.dp else [pair]
        for p in set(whitelist) | {pair}:
            sig = self._signals.get(p, {}).get(signal_ms)
            if sig is None or p in open_pairs:
                continue
            if p != pair and self._cannot_enter(p, sig["side"], signal_ms, live):
                continue
            candidates[p] = sig["score"]
        max_open = self.config.get("max_open_trades", 1)
        free = (float("inf") if max_open in (-1, None) else float(max_open)) - Trade.get_open_trade_count()
        bonus = float(self.p["ranking"]["binance_priority_bonus"])
        # bonus sadece dry-run/canlı: backtest bugünkü listeye ve saate bağlı olmasın
        bonus_pairs = self._binance.pairs() if bonus and live else frozenset()
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
            if self._reject(pair, current_time):  # mum başına bir log satırı; sıralamada yer açar
                logger.info("%s: derinlik yetersiz (+/-%%%.2f içinde %.0f USDT < %.0f), giriş reddedildi.",
                            pair, float(d["band_pct"]) * 100, notional, float(d["min_depth_usdt"]))
        return ok

    # ------------------------------------------------------------------ işlem yönetimi

    def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs) -> None:
        if order.ft_order_side == trade.exit_side:
            self._exits[pair] = (_ms(current_time), trade.trade_direction)
            return
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

    def custom_roi(self, pair: str, trade: Trade, current_time: datetime, trade_duration: int,
                   entry_tag: str | None, side: str, **kwargs) -> float | None:
        # hedef fiyat (tp) -> kâr oranı eşiği; backtest mum tepe/dibine göre mum içinde çıkar
        return core.target_roi(trade, trade.get_custom_data("tp"))

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs) -> str | None:
        held = (current_time - trade.open_date_utc).total_seconds() / 60
        return core.exit_reason(
            crossed=bool(trade.get_custom_data("fill_beyond_stop", False)), held_minutes=held,
            max_hold_minutes=float(self.p["max_hold_minutes"]),
        )
