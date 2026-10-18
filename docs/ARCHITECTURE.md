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
| (demo_status) | `/data/demo_status_mark.json` | `demo_status mark start\|stop` (10/11 .bat, compose up/stop öncesi) | `demo_status start\|stop` (okur, siler; en fazla 30 dk eski) |

Container'lara repodan sadece `cyberbot/` (salt okunur), `user_data/` ve `reports/` bağlanır; `.env`
hiçbir container'a girmez. Değerler compose `environment` ile gelir; WEEX anahtarlarını sadece
`conntest` servisi (bağlantı testi) alır.

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
config.json yorum içermez (düz JSON; `cyberbot.settings` json modülüyle okur).

## Strateji (`user_data/strategies/CyberScalp.py` + `cyberbot/strategy/`)

- Puan: etkin katmanların ağırlıklı ortalaması (0-100), giriş eşiği `entry_score_threshold` (70).
  Faz 1'de sadece `trend` katmanı var. Zorunlu koşullar puandan bağımsız: trend filtresi, kapanmış mum
  tetiği, stop mesafesi [`min_stop_pct`, `max_stop_pct`], brüt R/R ≥ `min_rr`, bilgi mumu tazelik kontrolü.
  Yatay rejimde (ADX < `adx_trend`) Faz 1 işlem açmaz.
- `min_rr` / `target_rr` BRÜT R/R'dir (ücretsiz). Teminat ücreti de hesaba katar:
  teminat = özsermaye × `risk_per_trade` / ((stop mesafesi + `round_trip_fee`) × kaldıraç), varsayılan
  `round_trip_fee` 0.002 (WEEX taker %0.08 × 2 + kayma payı).
- Çıkışlar: hedef `custom_roi` ile (`trade.calc_profit_ratio(tp)`), Freqtrade etiketi **`roi`** (raporda
  "hedef"); backtest hedefi mum içinde tepe/dip ile yakalar. `custom_exit` sadece `time_stop`
  (`max_hold_minutes`) ve `fill_beyond_stop`. Stop `custom_stoploss` + `stoploss_from_absolute`
  (etiket `stop_loss`; Freqtrade bazen `trailing_stop_loss` yazar, raporda birlikte sayılır).
- İşlem başına özel veri (`trade.set_custom_data`, giriş dolumunda): `sl, tp, rr, risk_pct, score,
  plan_source, fill_beyond_stop`.
- Sıralama: aynı mumda sinyal veren pariteler puana göre; kilitli/bu mumda kapanan/derinlik veya teminat
  yüzünden reddedilen pariteler aday sayılmaz. Binance önceliği bonusu sadece dry-run/canlıda.
- Sağlık: BTC 5m mum tazeliği; bozulunca `lock_pair('*', reason='exchange_down')` + tek Telegram mesajı;
  yeniden başlatmada eski kilit temizlenir ve açık kalan `exchange_down` olayı kapatılır.

## Uptime (`cyberbot/uptime.py`, `/data/uptime.sqlite`)

Tablolar `sessions` ve `events` (şema modülde). Bileşen adları: `freqtrade`, `recorder`.
Kalp atışı dakikada bir; freqtrade için sadece ana döngü son 3 dakikada ilerlediyse yazılır (açılışta 15 dk
tolerans). Kapanış türleri (`sessions.stop_kind`): normal olanlar `clean`, `reload`
(`uptime.NORMAL_STOP_KINDS`); `stalled` (ana döngü takıldı; bitince yeni oturum açılır), `crash:<İstisna>`
ve kapanış kaydı olmayan (elektrik/çökme) oturumlar anormaldir. `clean`/`reload` sonrası boşluk planlı
durdurmadır: raporda uptime %'sine sayılmaz ama o dönemdeki işlemler yine "kesintili" diye ayrılır.
Olay türleri (`events.kind`):

| kind | yazan | anlamı |
| --- | --- | --- |
| `exchange_down` / `exchange_recovered` | strateji | WEEX verisi bayatladı → yeni işlem kilitlendi / düzeldi |
| `weex_unreachable` / `weex_recovered` | monitor | WEEX REST'e ulaşılamıyor / düzeldi |
| `bot_stale` / `bot_recovered` | monitor | freqtrade kalp atışı durdu (süreç yok veya ana döngü durdurulmuş/takılmış, ör. Telegram /stop) / geri geldi. En yeni oturum `clean` kapandıysa uyarı yok |
| `task_failing` / `task_recovered` | monitor | kaydedici işi (WS, doldurma, zamanlanmış iş) üst üste hata veriyor / düzeldi |
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

`avail_ms` kuralları:
- `bn_futures_data`: `ts_ms + periyot + 60 sn` (deterministik; canlıda ve geçmiş doldurmada aynı).
- `weex_premium`, `weex_oi`: `recv_ms`.
- `weex_funding_hist`: ödemeden en fazla 30 dk sonra (canlı) çekilen satır `max(recv_ms, funding_ms + 2 dk + 60 sn)`;
  sonradan toplu çekilen geçmiş `funding_ms + 2 dk + 60 sn`. Satır tekrar çekilirse ilk değer korunur.
- `bn_liq_1m`, `bn_liq_coverage_1m`: satırın ilk yazıldığı an (en erken `bucket_ms + 60 sn`); yeniden
  hesaplamada değer değişirse (geç gelen likidasyon, kapsamanın sonradan düşmesi) yeni yazma anı.

Likidasyon kuralı: `bn_liq_1m` seyrektir, sadece likidasyon olan (sembol, dakika) satırları vardır.
Dakikanın WS kapsaması (tüm semboller için ortak) `bn_liq_coverage_1m`'dedir. `bn_liq_1m` satırı yok ve
kapsama > 0 ise o dakika likidasyon 0'dır; kapsama satırı yoksa veya kapsama 0 ise veri yoktur (NaN, 0 değil).
Kapsama < 1 ise dakikanın sadece bir kısmı dinlenmiştir. Akış alt sınırdır (Binance sembol başına saniyede en
fazla 1 emir yollar). Abonelik onayı gelmeyen veya 10 dk hiç mesaj göndermeyen bağlantı kapsama sayılmaz.

| Tablo | Birincil anahtar | Önemli sütunlar |
| --- | --- | --- |
| `symbol_map` | `weex_symbol` | `ft_pair, binance_symbol (NULL=yok), multiplier, method, price_ratio, binance_onboard_ms, verified_ms, active` |
| `bn_futures_data` | `(symbol, period, ts_ms)` | `oi_qty, oi_value, gl_ratio, gl_long, gl_short, ta_ratio, ta_long, ta_short, tp_ratio, tp_long, tp_short, tk_ratio, tk_buy_vol, tk_sell_vol, avail_ms, first_seen_ms, updated_ms` |
| `bn_liquidations` | `(symbol, trade_ms, side, price, qty)` | `event_ms, avg_price, last_qty, filled_qty, status, notional, recv_ms, conn_id` (sadece `st==1`, UM) |
| `bn_liq_1m` | `(symbol, bucket_ms)` | `long_liq_usd, short_liq_usd, n_long, n_short, max_usd, coverage, avail_ms` (seyrek: sadece likidasyon olan dakikalar) |
| `bn_liq_coverage_1m` | `bucket_ms` | `coverage, avail_ms` (her dakikanın WS kapsaması 0..1) |
| `weex_premium` | `(symbol, bucket_ms)` | `server_ms, recv_ms, mark, idx, last_funding, forecast_funding, next_funding_ms, collect_cycle_min, avail_ms` |
| `weex_funding_hist` | `(symbol, funding_ms)` | `rate, mark, recv_ms, avail_ms` |
| `weex_oi` | `(symbol, bucket_ms)` | `server_ms, recv_ms, oi_raw, mark, avail_ms` |
| `ws_sessions` | `conn_id` | `url, open_ms, close_ms, reason` |
| `heartbeat` | `component` | `last_ok_ms, last_err_ms, last_err, consecutive_fail` |
| `gaps` | `id` (+ UNIQUE `source, symbol, start_ms`) | `end_ms, reason, detected_ms, state (open/backfilled/unrecoverable)` |
| `bn_backfill_checked` | `(symbol, endpoint, start_ms)` | `end_ms, checked_ms` (Binance'e sorulup cevap alınan doldurma aralıkları; orada olmayan veri tekrar sorulmaz) |
| `meta` | `key` | `value` (schema_version) |
| `fetch_log` | — | `ts_ms, endpoint, symbol, http, ms, rows, used_weight, low` (7 günden eskisi silinir) |

`gaps` (bn_futures): eksik 29.5 günlük geçmişi olan her Binance sembolü için bir `open` satır (yeni sembol dahil);
doldurma bitip canlı veri yetişince `backfilled`. Doldurma DB'deki eksik periyotlardan planlanır (açılışta ve
saatte bir), yarıda kalan doldurma yeniden başlatmadan sonra devam eder.

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
