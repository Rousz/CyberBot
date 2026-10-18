# PROGRESS – CyberBot (WEEX USDT-M scalp botu, Freqtrade tabanlı)

Son güncelleme: 2026-10-18 UTC. Yeni oturum buradan devam eder. Teknik sözleşme: `docs/ARCHITECTURE.md`.

## Şu an: Faz 1 – İlk çalışan demo bot (dry-run)

Durum: **VM tarafı bitti (298 internetsiz test geçiyor), PC'de test bekleniyor.**

### PC sonuçları
- 2026-10-18 12:11 UTC `00_quick_check.bat` (kullanıcı sohbete yapıştırdı): **BAŞARILI**. Türkiye'den WEEX web,
  WEEX vadeli REST (0.72 sn) ve spot REST, Binance vadeli REST (451 yok), data.binance.vision, Telegram API ve
  Docker Hub erişilebilir. → Erişim engeli riski yok; Docker kurulumuna geçilebilir.
- Henüz yok: `01_connection_test` (Docker gerekli), `02_weex_probe`, demo.

### PC'de sırada (kullanıcı)
1. `docs/SETUP_WINDOWS.md` Adım 4-8: SVM/BIOS, WSL2, Docker Desktop, `setup_wslconfig.bat`, `setup_env.bat`
   (Telegram token) → `01_connection_test.bat` (chat id ekranda çıkar → .env → tekrar çalıştır).
2. `02_weex_probe.bat` → `reports/weex_probe_*.txt` + `reports/samples/probe_*.json` push.
3. `10_demo_start.bat` (demo başlar, arka planda haftalarca çalışır) → haftada bir `12_demo_report.bat` → push.
4. Her güncellemeden sonra: GitHub Desktop Pull → `10_demo_start.bat` (kodu yeniden yükler, botu yeniden başlatır).

### VM'de sırada
1. Probe sonuçlarını yorumla; `freqtrade_ext/weex.py` varsayımlarını doğrula/düzelt (historyKlines ilk/son 100 ve
   endTime dahil mi, son kline satırı oluşan mum mu, fundingRate ilk/son kayıtlar, depth limitleri, OI birimi,
   Binance `/futures/data` zaman damgası anlamı → `bn_futures_data.avail_ms` güvenlik payı).
2. `reports/samples/` gerçek cevaplarıyla `tests/fixtures/` güncelle.
3. Faz 2: veri indirme (WEEX historyKlines, yetmezse Binance verisi + iki borsa fiyat farkı raporu), sabit top-40
   backtest listesi (+ survivorship bias notu), `20_download_data.bat`, `21_backtest.bat`, PC'de lookahead/recursive
   analiz.
4. Faz 3: indikatör katmanı (B), Faz 4: formasyonlar (C, sentetik veriyle birim testli), Faz 5: türev verisi puanı
   (D; kaydedici verisinden, `avail_ms` kuralıyla), Faz 6: haber/makro (E; doküman devamı bekleniyor),
   Faz 7: haftalarca demo + katman etkisi ölçümü, canlı kararı.

### Bekleyenler / açık sorular (kullanıcı)
- Görev dokümanı "E) Haber ve makro – Ekonomik takvim: CPI, FOMC, NFP gibi saati" kısmında kesik geldi; devamı bekleniyor.
- Repo **public** → kullanıcı private yapacak (SETUP_WINDOWS Adım 1).
- Bu dalda eski "Synora Music Group" site dosyaları duruyor; silme için açık onay bekleniyor (README'nin altı da o site).
- VM'den doküman sitelerine (weex.com/api-doc, developers.binance.com) erişim izni cevapsız → erişilmiyor.
- Telegram: kullanıcının token'ı var, chat id yok → `01_connection_test.bat` ekranda gösterir.

## Biten işler
- **Faz 0:** repo iskeleti, `.gitignore`/`.gitattributes`, Windows kurulum rehberi, `00`/`01` bağlantı testleri.
- **Faz 1:**
  - `freqtrade_ext/weex.py` (Freqtrade Weex sınıfı) + `docker/Dockerfile` (Freqtrade 2026.9 + ccxt 4.5.88 + kayıt).
  - `CyberScalp` stratejisi: trend/rejim filtresi, EMA20 geri çekilme tetiği, swing+ATR stop, brüt R/R kontrollü hedef,
    risk bazlı teminat (ücret dahil), puan sıralaması, Binance önceliği, derinlik kontrolü, WEEX sağlık kilidi +
    Telegram, uptime kalp atışı.
  - Kaydedici (`cyberbot/recorder`): Binance OI/long-short/taker (+29.5 gün geçmiş doldurma), likidasyon akışı,
    WEEX funding/OI → `derivs.sqlite`; kendi istek sınırlayıcısı; izleme uyarıları (WEEX'e ulaşılamıyor, bot çalışmıyor).
  - PC araçları: `02_weex_probe`, `10/11` demo başlat/durdur (oturum kimliğiyle doğrulama), `12` demo raporu
    (uptime %, planlı/plansız kesinti, kesintili işlemler ayrı, R katı, drawdown…), `docs/DEMO_TEST.md`.
  - İnternetsiz testler: gerçek Freqtrade kodu + WEEX router; Backtesting, LookaheadAnalysis (bias yok),
    RecursiveAnalysis sentetik veride.
  - Çok açılı inceleme (5 inceleyici + doğrulayıcı): 25 gerçek bulgu düzeltildi.

## Kararlar
- WEEX entegrasyonu **(a) Freqtrade exchange alt sınıfı** (ccxt.weex): pozisyon/bakiye tek kaynakta.
- Demo başlangıç bakiyesi 1000 USDT; kaldıraç 3x isolated; max 3 açık işlem; risk/işlem %1.
- Veritabanları Docker volume `cyberbot_data`'da (`/data`); Windows klasöründe SQLite kilit sorunu olmasın diye.
- Container'lar `.env`'i görmez; WEEX anahtarlarını sadece `conntest` servisi alır.
- Canlı işlem kodda kapalı (`RunMode.LIVE` → hata).

## Canlı öncesi yapılacaklar (canlı kilidi kaldırılmadan önce hepsi)
- `_set_leverage`: `params={'marginMode': 'isolated'}` (yoksa ccxt cross kaldıraç ayarlar); ayarlananları önbellekle.
- Emir durumları: WEEX `partial_fill` → ccxt 'closed', `partially_filled` eşlenmemiş → filled < amount ise 'open'.
- Hata `-3200` (emir bulunamadı) → yeni emirler için yeniden denenebilir hata.
- Borsada stop (algo emirleri): `fetch_stoploss_order` / `cancel_stoploss_order` override (`trigger: True`,
  `actualOrderId` takibi), sonra `stoploss_on_exchange: true`.
- Funding geçmişi (`fetch_funding_history`, varsayılan 20 kayıt) ve `fetch_my_trades` sayfalama.
- `additional_exchange_init`: tek yönlü pozisyon modunu (COMBINED) kontrol et.
- `liquidatePrice == 0` → None; bakım marjı oranını (MMR, şimdi %1 varsayım) canlı pozisyonla kalibre et.
- Küçük gerçek emirle miktar biriminin (baz coin) ve reduceOnly/positionSide davranışının doğrulanması.
- Türkiye'de sabit IP'li VPS + API anahtarında IP kısıtlaması.

## Bilinen Faz 1 sınırlamaları
- Yatay rejimde (ADX < 20) işlem yok (destek/direnç Faz 4'te).
- Göstergeler/formasyonlar/türev/haber katmanları henüz yok; puan sadece trend katmanından.
- Likidasyon akışı alt sınırdır (Binance sembol başına saniyede 1 kayıt); WEEX OI biriminin doğrulanması bekliyor.
- Backtest'te `custom_exit` (time_stop) mum açılışında değerlendirilir; hedef (ROI) mum içinde yakalanır.
- Binance önceliği bonusu backtest'te uygulanmaz (sonuçlar tekrarlanabilir olsun diye).
- RecursiveAnalysis: startup 400'de EMA200 sapması < %1 (5m ~%0.05, 1h ~%0.5); PC analizinden sonra 600-1000 düşünülebilir.

## Teknik notlar (doğrulanmış)
- Freqtrade **2026.9** imajı: Python 3.14, ccxt 4.5.84 (imajda 4.5.88'e yükseltiliyor), websockets 17.1.
  4.5.84 WEEX'in `{"code":"200","msg":"success"}` cevaplarını hata sayıyor ve bozuk piyasa kaydında load_markets düşüyor.
- ccxt.weex: miktarlar baz coin birimi, `contractSize=contractVal` yanlış → `get_contract_size()=1`.
  Kaldıraç kademesi yok → `get_max_leverage()` piyasa limitinden. `klines` `since`'i yok sayar (son ≤1000 mum);
  geçmiş `historyKlines` (istek başına 100, startTime/endTime). ticker/24hr'de bid/ask yok → bookTicker ile birleştirilir.
- WEEX: REST `https://api-contract.weex.com/capi/v3/...`, WS `wss://ws-contract.weex.com/v3/ws/public`
  (User-Agent şart; `{"event":"ping"}` → `{"method":"PONG"}`). Piyasa yükleme spot host'a da bağlı (api-spot).
- Binance USDⓈ-M WS (2026 bölünmesi): `/public/ws` (depth, bookTicker, trade), `/market/ws` (kline, aggTrade,
  markPrice, forceOrder), `/private/ws`. Likidasyon akışında UM için `st==1`.
- Binance `/futures/data/*`: sadece son 30 gün, ayrı IP limiti 1000 istek / 5 dk (ccxt modellemiyor).
- Kurallar: VM'den borsalara istek yok; testler internetsiz. Zamanlar UTC, raporlarda İstanbul da.

## Dosya haritası
| Yol | Ne |
| --- | --- |
| `00_quick_check.bat`, `01_connection_test.bat` | Erişim / bağlantı testleri |
| `02_weex_probe.bat` | WEEX ayrıntılı davranış probu (`cyberbot/weex_probe.py`) |
| `10_demo_start.bat`, `11_demo_stop.bat`, `12_demo_report.bat` | Demo test (`cyberbot/demo_status.py`, `demo_report.py`) |
| `setup_env.bat`, `setup_wslconfig.bat`, `setup/` | Kurulum yardımcıları |
| `docker/Dockerfile`, `docker-compose.yml` | İmaj ve servisler (freqtrade, recorder, tools, conntest) |
| `freqtrade_ext/weex.py` | Freqtrade WEEX borsa sınıfı |
| `user_data/config.json`, `config.backtest.json` | Tek config + backtest katmanı |
| `user_data/strategies/CyberScalp.py`, `cyberbot/strategy/` | Strateji ve saf mantık |
| `cyberbot/recorder/` | Türev verisi kaydedici + izleme |
| `cyberbot/` (diğer) | paths, settings, uptime, notify, launch, report, timeutil, connection_test |
| `tests/` | İnternetsiz testler (`weex_router.py`, fixture'lar) |
| `docs/` | SETUP_WINDOWS, DEMO_TEST, ARCHITECTURE |
| `reports/` | Özetler (repoya girer); `reports/logs/` girmez |

## VM'de test
```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
