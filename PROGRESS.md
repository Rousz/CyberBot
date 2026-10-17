# PROGRESS – CyberBot (WEEX USDT-M scalp botu, Freqtrade tabanlı)

Son güncelleme: 2026-10-17 UTC. Yeni oturum buradan devam eder.

## Şu an: Faz 0 – Kurulum ve bağlantı testi

Durum: VM tarafı bitti, **PC'de test bekleniyor**.

### Bitti
- Plan onaylandı. Demo başlangıç bakiyesi **1000 USDT**. Kaldıraç varsayılan 3x, isolated.
- Karar: WEEX entegrasyonu **(a) Freqtrade exchange alt sınıfı** (ccxt.weex üzerinden). Gerekçe:
  pozisyon/bakiye tek kaynakta (Freqtrade) kalır; (b)'deki iki kaydın kayması riski yok.
- Repo iskeleti, `.gitignore`/`.gitattributes`, `.env.example`, `docker-compose.yml`.
- Windows kurulum rehberi: `docs/SETUP_WINDOWS.md`.
- `00_quick_check.bat` (Docker'sız curl kontrolü), `01_connection_test.bat` →
  `cyberbot/connection_test.py` (WEEX web/REST/WS/ccxt, Binance REST/yeni WS, Telegram).
- `setup_env.bat`, `setup_wslconfig.bat` (6 GB RAM / 4 çekirdek sınırı).
- VM birim testleri (`tests/`), ağ erişimi testlerde engelli.

### Sırada
1. PC: `docs/SETUP_WINDOWS.md` adımları → `00_quick_check.bat` → `01_connection_test.bat` → `reports/` push.
2. VM: sonuçları yorumla; `reports/samples/` gerçek cevaplarıyla `tests/fixtures/` güncelle;
   WEEX 5m geçmiş derinliğine göre backtest veri kaynağını seç (WEEX mi Binance mı).
3. Faz 1: WEEX exchange alt sınıfı + en basit strateji (trend filtresi + stop + R/R ≥ 1.5) +
   dry-run + Telegram + dinamik top-40 + bağlantı kopunca yeni işlem yok + açılış/kapanış (uptime)
   kaydı + türev verisi kaydedici (SQLite, sadece veri toplar).

### Bekleyenler / açık sorular
- Görev dokümanı "E) Haber ve makro – Ekonomik takvim: CPI, FOMC, NFP gibi saati" kısmında
  kesik geldi; **devamı kullanıcıdan bekleniyor** (Faz 6 ve sonrası buna bağlı).
- Repo **public** → kullanıcı private yapacak (rehber Adım 1).
- Bu dalda eski "Synora Music Group" site dosyaları duruyor (`src/`, `public/`, `package.json`...).
  Silmek için kullanıcı onayı bekleniyor. Site kodu `claude/synora-music-website-w1d3vk` dalında da var.
- VM'den doküman sitelerine (weex.com/api-doc, developers.binance.com) erişim izni sorulmuştu,
  cevap yok → erişilmiyor; adresler ccxt kaynak kodundan doğrulanıyor.
- Telegram: kullanıcının token'ı var, chat id yok → `01_connection_test.bat` ekranda gösterir.

## Teknik notlar (doğrulanmış)
- Freqtrade **2026.9** imajı `freqtradeorg/freqtrade:2026.9`: Python 3.14, ccxt 4.5.84,
  websockets 17.1, requests 2.34.2. Freqtrade ≥ ccxt 4.5.76 ister; weex 4.5.76'da da var.
- ccxt.weex (API v3): swap ✓, setLeverage ✓, setMarginMode ✓, fetchPositions ✓, stop/TP emirleri ✓,
  fetchFundingRateHistory ✓, fetchOpenInterest ✓ (geçmişi ✗ → kendimiz kaydedeceğiz),
  fetchLeverageTiers ✗ (likidasyon fiyatı için Faz 1'de çözülecek), hedge mode ✗ (sorun değil).
  Demo (sim) modu var: `capi/v3/sim/...`.
- **Dikkat (Faz 1):** ccxt.weex `fetch_ohlcv` varsayılan uçta (`klines`) `since`'i yok sayar, en son
  ≤1000 mumu döner. Geçmiş için `params={'historical': True}` (`historyKlines`, istek başına 100 mum).
  Freqtrade alt sınıfında ele alınmalı.
- WEEX: REST `https://api-contract.weex.com/capi/v3/...`, WS `wss://ws-contract.weex.com/v3/ws/public`
  (User-Agent başlığı şart; sunucu `{"event":"ping"}` yollar, `{"method":"PONG"}` beklenir).
  Sembol biçimi `BTCUSDT`; ccxt'de `BTC/USDT:USDT`.
- Binance USDⓈ-M WS (2026 bölünmesi): `wss://fstream.binance.com/public/ws` (depth, bookTicker, trade),
  `/market/ws` (kline, aggTrade, markPrice, forceOrder), `/private/ws` (kullanıcı verisi).
- Binance türev verisi (sadece son 30 gün): `https://fapi.binance.com/futures/data/` +
  `openInterestHist`, `globalLongShortAccountRatio`, `topLongShortAccountRatio`,
  `topLongShortPositionRatio`, `takerlongshortRatio`.
- Kurallar: VM'den borsalara istek yok; testler internetsiz. Zamanlar UTC, raporlarda İstanbul da.
  Gizli bilgiler sadece PC'deki `.env`'de.

## Dosya haritası
| Yol | Ne |
| --- | --- |
| `00_quick_check.bat` | Docker'sız hızlı erişim kontrolü → `reports/quick_check_latest.txt` |
| `01_connection_test.bat` | Tam bağlantı testi (Docker) → `reports/connection_test_*.txt` |
| `setup_env.bat`, `setup_wslconfig.bat` | Tek seferlik kurulum yardımcıları |
| `setup/` | .bat yardımcıları, `wslconfig.txt` |
| `cyberbot/` | Python paketi (rapor, zaman, bağlantı testi; sonra strateji modülleri) |
| `tests/` | VM birim testleri + fixture'lar |
| `docs/SETUP_WINDOWS.md` | PC kurulum rehberi |
| `reports/` | Özetler (repoya girer); `reports/logs/` ayrıntılı loglar (girmez) |

## VM'de test
```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
