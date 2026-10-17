# CyberBot mimarisi (teknik sözleşme)

Bu dosya modüller arası sözleşmedir: yollar, veritabanı şemaları, config bölümleri, kurallar.
Bir modülün dışa açık davranışı değişirse önce burası güncellenir.

## Bileşenler (docker-compose.yml)

| Servis | Çalıştırdığı | Görev |
| --- | --- | --- |
| `freqtrade` | `python -m cyberbot.launch trade --dry-run ... --strategy CyberScalp` | Demo test (dry-run). API anahtarı almaz. |
| `recorder` | `python -m cyberbot.recorder` | Türev verisini SQLite'a kaydeder + izleme (bot/WEEX erişimi) uyarıları |
| `tools` | `python -m <modül>` (profil: tools) | Tek seferlik işler: bağlantı testi, WEEX probu, rapor |

Hepsi aynı imajı kullanır: `docker/Dockerfile` = Freqtrade 2026.9 + ccxt 4.5.88 + `freqtrade_ext/weex.py`
(imajda `freqtrade/exchange/weex.py` olarak kopyalanır ve `freqtrade.exchange.Weex` olarak kaydedilir).
Repo container'da `/repo` (bind mount), veritabanları `/data` (Docker volume `cyberbot_data`).

## Yollar (`cyberbot/paths.py`)

| Fonksiyon | Container'da | Yazan | Okuyan |
| --- | --- | --- | --- |
| `config_path()` | `/repo/user_data/config.json` | kullanıcı/repo | hepsi |
| `trades_db()` | `/data/tradesv3.dryrun.sqlite` | freqtrade | rapor |
| `uptime_db()` | `/data/uptime.sqlite` | freqtrade (strateji), recorder | rapor, monitor |
| `derivs_db()` | `/data/derivs.sqlite` | recorder (tek yazar) | strateji (Faz 5), rapor |
| `binance_perps_json()` | `/data/binance_perps.json` | recorder | strateji |
| `reports_dir()` | `/repo/reports` | tools scriptleri | kullanıcı (git) |

VM testlerinde `CYBERBOT_DATA_DIR`, `CYBERBOT_CONFIG`, `CYBERBOT_REPORTS_DIR` ortam değişkenleriyle geçici
klasörlere yönlendirilir.

## Config (tek dosya: `user_data/config.json`)

Freqtrade ayarları + `"cyberbot"` bölümü. Her modül kendi varsayılanlarını tutar,
`cyberbot.settings.section(ad, VARSAYILANLAR, config)` ile birleştirir:

```json
"cyberbot": {
  "strategy": { ... },   // cyberbot/strategy (STRATEGY_DEFAULTS)
  "recorder": { ... },   // cyberbot/recorder (RECORDER_DEFAULTS)
  "monitor":  { ... }    // cyberbot/recorder/monitor.py (MONITOR_DEFAULTS)
}
```
Backtest için ek katman: `user_data/config.backtest.json` (StaticPairList; dinamik pairlist backtest'te çalışmaz).

## Uptime (`cyberbot/uptime.py`, `/data/uptime.sqlite`)

Tablolar `sessions` ve `events` (şema modülde). Bileşen adları: `freqtrade`, `recorder`.
Olay türleri (`events.kind`):

| kind | yazan | anlamı |
| --- | --- | --- |
| `exchange_down` / `exchange_recovered` | strateji | WEEX verisi bayatladı → yeni işlem kilitlendi / düzeldi |
| `weex_unreachable` / `weex_recovered` | monitor | WEEX REST'e ulaşılamıyor / düzeldi |
| `bot_stale` / `bot_recovered` | monitor | freqtrade kalp atışı durdu / geri geldi |
| `binance_unreachable` / `binance_recovered` | recorder | Binance verisi alınamıyor / düzeldi |

## binance_perps.json (recorder yazar, strateji okur)

```json
{"generated_ms": 1776000000000,
 "pairs": {"BTC/USDT:USDT": {"binance_symbol": "BTCUSDT", "multiplier": 1.0, "method": "exact"},
           "PEPE/USDT:USDT": {"binance_symbol": "1000PEPEUSDT", "multiplier": 1000.0, "method": "prefix_1000"}}}
```
Anahtar Freqtrade (ccxt) parite adıdır. Listede olmayan parite Binance'te yok sayılır.
Dosya yoksa veya 48 saatten eskiyse strateji Binance önceliği bonusunu uygulamaz.

## derivs.sqlite şeması (recorder sahibi; rapor ve strateji salt okunur)

Tüm zamanlar UTC ms tamsayı. `avail_ms` = verinin canlıda kullanılabilir olduğu an; strateji sadece
`avail_ms <= mum kapanışı` olan satırları kullanır (lookahead yok). WAL modu, tek yazar.

| Tablo | Birincil anahtar | Önemli sütunlar |
| --- | --- | --- |
| `symbol_map` | `weex_symbol` | `ft_pair, binance_symbol (NULL=yok), multiplier, method, price_ratio, binance_onboard_ms, verified_ms, active` |
| `bn_futures_data` | `(symbol, period, ts_ms)` | `oi_qty, oi_value, gl_ratio, gl_long, gl_short, ta_ratio, ta_long, ta_short, tp_ratio, tp_long, tp_short, tk_ratio, tk_buy_vol, tk_sell_vol, avail_ms, first_seen_ms, updated_ms` |
| `bn_liquidations` | `(symbol, trade_ms, side, price, qty)` | `event_ms, avg_price, last_qty, filled_qty, status, notional, recv_ms, conn_id` (sadece `st==1`, UM) |
| `bn_liq_1m` | `(symbol, bucket_ms)` | `long_liq_usd, short_liq_usd, n_long, n_short, coverage, avail_ms` |
| `weex_premium` | `(symbol, bucket_ms)` | `server_ms, recv_ms, mark, idx, last_funding, forecast_funding, next_funding_ms, collect_cycle_min, avail_ms` |
| `weex_funding_hist` | `(symbol, funding_ms)` | `rate, mark, recv_ms, avail_ms` |
| `weex_oi` | `(symbol, bucket_ms)` | `server_ms, recv_ms, oi_raw, mark, avail_ms` |
| `ws_sessions` | `conn_id` | `url, open_ms, close_ms, reason` |
| `heartbeat` | `component` | `last_ok_ms, last_err_ms, last_err, consecutive_fail` |
| `gaps` | `id` (+ UNIQUE `source, symbol, start_ms`) | `end_ms, reason, detected_ms, state (open/backfilled/unrecoverable)` |

`symbol` sütunları borsanın kendi kimliğidir (Binance tablolarında `BTCUSDT`, WEEX tablolarında `BTCUSDT`).

## Kurallar

- Sinyaller sadece kapanmış mumlarla; `shift(-n)`, merkezli pencere, tüm sütun üzerinden normalizasyon yasak.
  Bilgi zaman dilimleri yalnızca `@informative` / `merge_informative_pair` ile birleştirilir.
- Yan etkiler (Telegram, dosya/DB yazma, ağ) sadece `dp.runmode in (RunMode.DRY_RUN, RunMode.LIVE)` iken.
  Backtest/hyperopt/lookahead analizinde ağa çıkılmaz.
- Strateji borsaya veya Binance'e kendisi istek atmaz; türev verisini sadece `derivs.sqlite`'tan okur.
- Kullanıcıya giden metinler Türkçe. Strateji Telegram'ı `dp.send_msg(..., always_send=True)` ile kullanır
  ve değişken metinleri `cyberbot.notify.md_escape` ile kaçışlar; diğer süreçler `cyberbot.notify.TelegramNotifier`.
- Gizli bilgiler sadece PC'deki `.env`'de; hiçbir log/rapor satırına yazılmaz.
- Canlı işlem `freqtrade_ext/weex.py` içinde `RunMode.LIVE` için kapalıdır (PROGRESS.md "canlı öncesi" listesi).
- Testler internetsiz: `tests/conftest.py` ağ engeli, WEEX için `tests/weex_router.py`.
