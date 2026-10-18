# Demo test rehberi (Faz 1)

Bu rehber botun **demo testini** (sanal parayla deneme) bilgisayarında başlatmak,
haftalarca çalıştırmak, durdurmak ve sonuçları bana getirmek içindir.
Önce `docs/SETUP_WINDOWS.md` adımlarının bitmiş ve `01_connection_test.bat`'ın
`SONUÇ: BAŞARILI` vermiş olması gerekir.

## Demo test ne yapar?

| Konu | Açıklama |
| --- | --- |
| Para | **Sanal 1000 USDT**. Gerçek para yok, WEEX hesabına hiçbir emir gitmez. |
| API anahtarı | **Gerekmez.** WEEX satırları `.env` içinde boş kalabilir. |
| Fiyatlar | WEEX'in gerçek, canlı fiyatları (herkese açık piyasa verisi). |
| İşlem türü | USDT-M sürekli vadeli (perpetual), **3x kaldıraç, isolated**, hem **long** hem **short**. |
| Pariteler | WEEX'te hacmi en yüksek ~40 parite, saatte bir yenilenir. |
| Kaydedici | Ayrı bir program (recorder) Binance/WEEX türev verisini kaydeder ve bot durursa Telegram'dan uyarır. |
| Kayıtlar | Her açılış/kapanış ve her dakika "çalışıyorum" kaydı tutulur; kesintiler raporda ayrı gösterilir. |

Bot bilgisayarında Docker içinde, **arka planda** çalışır. Pencereyi kapatman botu durdurmaz.

## Bir kez: WEEX probu

Demo testten önce bir kez `02_weex_probe.bat` dosyasına çift tıkla (5-10 dakika sürer).
WEEX ve Binance'in botun doğru çalışması için önemli davranışlarını ölçer; sadece herkese
açık veri okur. Sonuç `reports\weex_probe_<tarih>.txt` dosyasına ve `reports\samples\probe_*.json`
dosyalarına yazılır. Bunları bana gönder (aşağıda "Bana ne getirmeli").

`SONUÇ: BAŞARILI (uyarılarla)` normaldir; uyarıların anlamını ben yorumlayacağım.

## İlk başlatma

1. Docker Desktop açık olsun, sol altta yeşil **Engine running** yazsın.
2. `.env` içinde `TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` dolu olsun (`setup_env.bat`).
   Boşsa bot yine çalışır ama Telegram mesajı gelmez.
3. `C:\CyberBot\10_demo_start.bat` dosyasına çift tıkla.
4. İlk seferde imaj hazırlanır (birkaç dakika). Sonra en fazla 2 dakika açılış kontrol edilir.

Ne görmelisin:

- `bot (Freqtrade): yeni oturum ... açıldı` ve `kaydedici (recorder): yeni oturum ... açıldı`
- En sonda `SONUÇ: BAŞARILI` kutusu ve "Demo test ARKA PLANDA calisiyor".
- Telegram'a botun açılış mesajı gelir (İngilizce, ör. `Status: running`).
- Docker Desktop → **Containers** → `cyberbot` altında `freqtrade` ve `recorder` yeşil (**Running**).

`SONUÇ: HATA` görürsen: ekranda bir açıklama ve son log satırları çıkar.
`reports\demo_start_<tarih>.txt` dosyasını bana getir.

## Günlük kullanım

Hiçbir şey yapman gerekmez. Bot kendi kendine işlem açar ve kapatır.

- Telegram'dan arada bir `/status` ve `/profit` yazarak bakabilirsin.
- Haftada bir `12_demo_report.bat` ile rapor al ve bana gönder.
- Bilgisayarı kapatma; ekranın kapanması sorun değil (aşağıdaki güç ayarları).

## Telegram komutları

Komutları kendi botuna yaz (başında `/` ile). Cevaplar İngilizce gelir.

| Komut | Ne yapar |
| --- | --- |
| `/status` | Açık işlemler: parite, yön (long/short), giriş fiyatı, anlık kâr/zarar |
| `/profit` | Toplam kâr/zarar, işlem sayısı, kazanma oranı |
| `/balance` | Sanal bakiye (1000 USDT'den başlar) |
| `/daily` | Gün gün kâr/zarar |
| `/performance` | Parite başına kâr/zarar |
| `/stopentry` | **Yeni işlem açmayı durdurur**; açık işlemler normal şekilde yönetilmeye devam eder (`/stopbuy` ve `/pause` da aynı) |
| `/start` | `/stop` veya `/stopentry` sonrası botu tekrar normal çalışmaya alır |
| `/stop` | Botun işlem döngüsünü durdurur (açık işlemler **kapatılmaz**, sadece takip edilmez). Program açık kalır; `/start` ile devam eder |
| `/help` | Tüm komutların listesi |

`/stop` ve `/stopentry` bot yeniden başlayınca (bilgisayar yeniden açılınca ya da `10_demo_start.bat`)
sıfırlanır; bot normal çalışmaya döner.

Önerim: bir sorun görürsen önce `/stopentry` kullan, bana yaz. `/stop` yerine bilgisayardan
`11_demo_stop.bat` daha temizdir.

Bot ayrıca kendiliğinden mesaj atar: işlem açıldı/kapandı, "WEEX verisi alınamıyor, yeni işlem
yok" ve "düzeldi" mesajları; kaydedici de "Bot çalışmıyor" uyarısı gönderir.

## Durdurma

`11_demo_stop.bat` dosyasına çift tıkla. Bot ve kaydedici en fazla 1-2 dakikada düzgünce kapanır.
Ne görmelisin: iki satırda `temiz kapandı` ve `SONUÇ: BAŞARILI`.

- Veriler silinmez; `10_demo_start.bat` ile kaldığı yerden devam eder (açık sanal işlemler dahil).
- Durdurduktan sonra bilgisayar yeniden açılsa da bot **kendiliğinden başlamaz**.

## Rapor

`12_demo_report.bat` dosyasına çift tıkla (bot çalışırken de olur, botu etkilemez).
Sonuç `reports\demo_report_<tarih>.txt` dosyasına yazılır. İçinde:

- Dönem, botun ve kaydedicinin **çalışma süresi yüzdesi**, kesinti dönemleri, yeniden başlatmalar,
  WEEX/Binance kesinti olayları.
- İşlem sayısı, kazanma oranı, toplam kâr/zarar (USDT ve 1000 USDT'nin yüzdesi), kâr faktörü,
  ortalama R, en büyük düşüş, long/short ayrımı, çıkış nedenleri, en iyi/en kötü pariteler,
  açık işlemler, funding toplamı.
- **Kesintiye denk gelen işlemler ayrı listelenir ve sonuçlara katılmaz** (bot kapalıyken ya da
  WEEX verisi gelmezken açık olan işlemler adil değerlendirilemez).
- Türev verisi kaydının son 24 saatteki durumu.

Saatler hem UTC hem İstanbul saatiyle yazılır.

## Bana ne getirmeli

GitHub Desktop'ı aç → solda yeni dosyalar listelenir → **Summary** kutusuna kısa bir not yaz
(ör. `demo hafta 1`) → **Commit** → **Push origin**. Gönderilecekler (hepsi `reports\` altında):

| Dosya | Ne zaman |
| --- | --- |
| `weex_probe_<tarih>.txt` ve `samples\probe_*.json` | Prob çalıştırınca (bir kez) |
| `demo_start_<tarih>.txt` | Her başlatmada, özellikle HATA varsa |
| `demo_stop_<tarih>.txt` | Her durdurmada |
| `demo_report_<tarih>.txt` | Haftada bir |
| `*_error.txt` | Bir .bat dosyası "SONUC: HATA" verdiyse |

> Listede `.env` görürsen **durdur**, commit etme ve bana haber ver. `reports\logs\` klasörü ve
> veritabanları zaten GitHub'a gitmez. Ayrıntılı log isteyeceğim zaman ayrıca söylerim.

## Haftalarca çalışma için Windows ayarları

Bilgisayar uykuya geçerse bot da durur. Bir kez şu ayarları yap:

1. **Uyku kapalı:** Ayarlar → Sistem → Güç (ve pil) → **Ekran ve uyku** →
   "Prize takılıyken, cihazımı şu süreden sonra uyku moduna geçir": **Hiçbir zaman**.
   Ekranın kapanma süresi serbest (ekranın kapanması sorun değil).
2. **Hazırda bekletme kapalı:** Denetim Masası → Güç Seçenekleri → seçili planda
   **Plan ayarlarını değiştir** → **Gelişmiş güç ayarlarını değiştir** → Uyku →
   "Şu süreden sonra hazırda beklet": **Hiçbir zaman** (Uyku → "Şu süreden sonra uyu": **Hiçbir zaman**).
   Dizüstü bilgisayarsa: "Kapağı kapatma eylemi" → prize takılıyken **Hiçbir şey yapma**.
3. **Windows Update:** Ayarlar → Windows Update → Gelişmiş seçenekler → **Kullanım saatleri**:
   elle, bilgisayarı en çok kullandığın saatleri seç (Windows bu saatlerde yeniden başlatmaz).
   Güncelleme yeniden başlatması yine de olabilir; aşağıdaki maddeye bak.
4. **Yeniden başlatmadan sonra:** Docker Desktop **oturum açınca** başlar
   (`SETUP_WINDOWS.md` Adım 5'teki "Start Docker Desktop when you sign in" işareti).
   Bot da onunla birlikte kendiliğinden açılır. Windows giriş ekranında beklerse bot çalışmaz:
   - Ayarlar → Hesaplar → Oturum açma seçenekleri → **"Güncelleştirmeden sonra cihazımın kurulumunu
     otomatik olarak bitirmek için oturum açma bilgilerimi kullan"** seçeneğini aç (varsa).
   - Bilgisayar yeniden başladıysa oturum aç, 2-3 dakika sonra Telegram'dan `/status` yaz.
5. Bilgisayarı **kapatma**; kapatman gerekirse önce `11_demo_stop.bat`.

## İnternet ya da elektrik kesilirse

- **İnternet kesilirse:** bot WEEX verisinin bayatladığını anlar ve **yeni işlem açmaz**.
  Açık sanal işlemler veri geri gelince yönetilmeye devam eder. İnternet geri gelince Telegram'a
  "kesinti" ve "düzeldi" mesajları gelir (internet yokken Telegram da çalışmaz).
  Kesinti raporda görünür ve o sırada açık olan işlemler sonuçlardan ayrılır.
- **Elektrik kesilirse / bilgisayar çökerse:** kapanış kaydı yazılamaz, rapor bunu
  "temiz olmayan kapanış" olarak gösterir. Bilgisayar açılıp oturum açınca Docker ve bot
  kendiliğinden başlar; bir şey yapman gerekmez.
- **WEEX kısa süre cevap vermezse:** bot birkaç kez dener, olmazsa aynı şekilde yeni işlem açmaz.

## Sorun giderme

| Belirti | Ne yapmalı |
| --- | --- |
| `SONUC: HATA - Docker Desktop calismiyor` | Docker Desktop'ı aç, **Engine running** yazısını bekle, tekrar dene |
| `SONUC: HATA - .env dosyasi yok` | `setup_env.bat` çalıştır, Telegram bilgilerini yaz, kaydet |
| `bot (Freqtrade): henüz hiç oturum kaydı yok` | WEEX'e erişim olmayabilir. 2-3 dakika bekleyip `10_demo_start.bat`'ı tekrar çalıştır; düzelmezse `demo_start` dosyasını bana getir |
| Docker Desktop'ta `freqtrade` sürekli **Restarting** | Bot açılırken hata alıyor; `10_demo_start.bat` çıktısını ve `demo_start` dosyasını getir |
| Telegram'dan mesaj gelmiyor | `.env`'de `TELEGRAM_CHAT_ID` dolu mu? `01_connection_test.bat` ile kontrol et, sonra `11_demo_stop.bat` + `10_demo_start.bat` |
| Telegram'da komutlara cevap yok | Bot kapalı olabilir: Docker Desktop'ta `freqtrade` **Running** mi? Değilse `10_demo_start.bat` |
| "Bot çalışmıyor" uyarısı geldi | Bilgisayar uykuya mı geçti? Docker Desktop açık mı? `10_demo_start.bat` |
| Raporda uptime %95'in altında | Güç ayarlarını ve Windows Update kullanım saatlerini kontrol et; raporu bana gönder |
| Raporda "henüz işlem yok" | Normal olabilir: bot sadece kurallarına uyan fırsatta işlem açar. Birkaç gün bekle |
| `demo_stop`: "kapanış kaydı yok" | Zararsız (kayıp yok); tekrarlarsa bana bildir |
| Bilgisayar çok yavaşladı | Docker en fazla 6 GB RAM kullanır (`setup_wslconfig.bat`). Yine yavaşsa bana yaz |
