# Windows kurulum rehberi (test bilgisayarı)

Bu rehber bir kez yapılır. Sıra önemli; her adımın sonunda "ne görmelisin"
yazıyor. Takılırsan o adımın ekran görüntüsünü veya hata metnini bana getir.

Kurulacaklar (hepsi ücretsiz):

| Program | Ne işe yarar |
| --- | --- |
| GitHub Desktop | Kodu benden alır, test sonuçlarını bana gönderir |
| WSL2 | Windows içinde küçük bir Linux; Docker bunun üzerinde çalışır |
| Docker Desktop | Freqtrade'i ve botu kutu (container) içinde çalıştırır. Kişisel kullanım ücretsiz |

---

## Adım 1 – Repoyu private yap

Repo şu an herkese açık. Strateji ve ayarlar görünmesin diye:

1. Tarayıcıda https://github.com/Rousz/CyberBot adresini aç.
2. Üstte **Settings** → solda **General** → sayfanın en altında **Danger Zone**.
3. **Change repository visibility** → **Change to private** → onayla.

## Adım 2 – GitHub Desktop ve repoyu bilgisayara çekme

1. https://desktop.github.com adresinden GitHub Desktop'ı indir ve kur.
2. Açılınca **Sign in to GitHub.com** ile kendi hesabınla giriş yap.
3. **File → Clone repository** → **GitHub.com** sekmesi → `Rousz/CyberBot` seç.
4. **Local path** olarak `C:\CyberBot` yaz.
   - Önemli: "Belgeler", "Masaüstü" gibi OneDrive'a bağlı klasörleri ve içinde
     Türkçe karakter ya da boşluk olan yolları kullanma; Docker bunlarla sorun çıkarır.
5. **Clone**'a bas.
6. Üstteki **Current branch** menüsünden `claude/modest-fermat-6sc0qg` dalını seç.
7. Her yeni güncellememden sonra: **Fetch origin**, ardından **Pull origin**.

Ne görmelisin: `C:\CyberBot` klasöründe `00_quick_check.bat`, `01_connection_test.bat`,
`PROGRESS.md` gibi dosyalar.

## Adım 3 – Hızlı ön kontrol (Docker gerekmez)

`C:\CyberBot\00_quick_check.bat` dosyasına çift tıkla.

Ne görmelisin: her satırda `[OK]` ve en sonda `SONUC: BASARILI`.
Sonuç `reports\quick_check_latest.txt` dosyasına yazılır.

- `[HATA] ... bolge engeli` veya `erisim reddedildi` görürsen: o borsa bu bağlantıdan
  erişime kapalı olabilir. Devam et, ama bunu bana mutlaka bildir.
- VPN, proxy veya benzeri bir engel aşma yöntemi **kullanma**.

## Adım 4 – BIOS'ta sanallaştırma (SVM) kontrolü

Docker'ın çalışması için işlemcinin sanallaştırma özelliği açık olmalı.
AMD/ASUS kartlarda bu özellik genelde kapalı gelir.

1. **Ctrl + Shift + Esc** ile Görev Yöneticisi'ni aç → **Performans** → **CPU**.
2. Sağ altta **Sanallaştırma: Etkin** yazıyorsa bu adımı atla.
3. **Devre dışı** yazıyorsa:
   1. Bilgisayarı yeniden başlat; açılırken art arda **Del** (veya **F2**) tuşuna bas.
   2. ASUS BIOS açılır. **F7** ile **Advanced Mode**'a geç.
   3. **Advanced** → **CPU Configuration** → **SVM Mode** → **Enabled**.
   4. **F10** → **OK** (kaydet ve çık).
   5. Windows açılınca 1. maddeyi tekrar kontrol et: **Etkin** yazmalı.

## Adım 5 – WSL2 ve Docker Desktop

**WSL2:**

1. Başlat menüsüne `cmd` yaz → **Komut İstemi**'ne sağ tıkla → **Yönetici olarak çalıştır**.
2. Şunu yaz, Enter: `wsl --install --no-distribution`
3. Bitince bilgisayarı yeniden başlat.
4. Tekrar yönetici Komut İstemi aç, şunu yaz: `wsl --update`

**Docker Desktop:**

1. https://www.docker.com/products/docker-desktop/ → **Download for Windows – AMD64**.
2. Kurulumda **Use WSL 2 instead of Hyper-V** işaretli kalsın → **OK**.
3. İsterse bilgisayarı yeniden başlat.
4. Docker Desktop'ı aç → şartları kabul et → hesap açma ekranını **Skip** ile geç
   (hesap gerekmez).
5. Sağ üstteki dişli (**Settings**) → **General** →
   **Start Docker Desktop when you sign in to your computer** işaretli olsun
   (demo test haftalarca sürecek; bilgisayar açılınca Docker kendiliğinden başlasın).

Ne görmelisin: Docker Desktop penceresinin sol altında yeşil **Engine running**.

## Adım 6 – Docker'ın RAM kullanımını sınırla

Bilgisayarı başka işler için de kullandığın için Docker'ın en fazla 6 GB RAM ve
4 çekirdek kullanmasını sağlıyoruz.

1. `C:\CyberBot\setup_wslconfig.bat` dosyasına çift tıkla.
2. Sorularda **E**'ye bas. Önce Docker Desktop'ı kapatman istenir: saatin yanındaki
   balina simgesine sağ tıkla → **Quit Docker Desktop**.
3. İş bitince Docker Desktop'ı tekrar aç.

Ne görmelisin: `SONUC: BASARILI - .wslconfig yazildi`.

## Adım 7 – .env dosyası (gizli bilgiler)

1. `C:\CyberBot\setup_env.bat` dosyasına çift tıkla. Not Defteri açılır.
2. `TELEGRAM_TOKEN=` satırının sonuna BotFather'ın verdiği token'ı yapıştır
   (boşluk ve tırnak olmadan). Örnek: `TELEGRAM_TOKEN=123456789:AAH...`
3. `TELEGRAM_CHAT_ID=` satırını şimdilik **boş bırak**; bağlantı testi sana gösterecek.
4. WEEX satırlarını **boş bırak** (demo test için gerekmez).
5. **Ctrl + S** ile kaydet, Not Defteri'ni kapat.
6. Telegram'da kendi botunu aç (BotFather'ın verdiği `t.me/...` bağlantısı) ve
   **Start**'a bas ya da "merhaba" yaz. Chat id ancak bundan sonra bulunabilir.

`.env` dosyası GitHub'a hiçbir zaman gitmez. İçeriğini sohbete yapıştırma.

## Adım 8 – Bağlantı testi

1. Docker Desktop açık ve **Engine running** olsun.
2. `C:\CyberBot\01_connection_test.bat` dosyasına çift tıkla.
3. İlk seferde Freqtrade imajı indirilir (yaklaşık 300 MB). Sonra test 1-2 dakika sürer.

Ne görmelisin:

- WEEX, Binance ve Telegram için `[OK]` satırları. Birkaç `[BİLGİ]` ve `[ATLANDI]`
  satırı da olacak; bunlar normal.
- Telegram bölümünde yıldızlı bir kutu içinde **TELEGRAM CHAT ID** numarası.
  Bu numarayı `setup_env.bat` ile `.env` içindeki `TELEGRAM_CHAT_ID=` satırına yaz,
  kaydet ve `01_connection_test.bat`'ı **bir kez daha** çalıştır.
- İkinci çalıştırmada Telegram'a "CyberBot bağlantı testi: BAŞARILI" mesajı gelmeli.
- En sonda `SONUÇ: BAŞARILI` kutusu.

Sonuç `reports\connection_test_<tarih>.txt` dosyasına yazılır. `reports\samples\`
klasörüne de borsa cevaplarından küçük örnekler kaydedilir; bunlar herkese açık
piyasa verisidir ve VM'deki testlerimde kullanacağım.

## Adım 9 – Sonuçları bana gönder

**Yol 1 (tercih):** GitHub Desktop'ı aç. Solda `reports\` altındaki yeni dosyalar
listelenir. Sol altta **Summary** kutusuna `Faz 0 test sonuclari` yaz →
**Commit to claude/modest-fermat-6sc0qg** → üstte **Push origin**.

> Listede `.env` görürsen **durdur**, commit etme ve bana haber ver. (Görmemen gerekir.)

**Yol 2:** `reports\connection_test_<tarih>.txt` ve `reports\quick_check_latest.txt`
dosyalarını Not Defteri ile açıp içeriğini sohbete yapıştır.

---

## Sık karşılaşılan sorunlar

| Belirti | Çözüm |
| --- | --- |
| `SONUC: HATA - Docker Desktop calismiyor` | Docker Desktop'ı aç, **Engine running** yazısını bekle, tekrar dene |
| Docker: "Virtualization support not detected" | Adım 4'teki SVM ayarı |
| Docker: "WSL 2 installation is incomplete" | Yönetici Komut İstemi'nde `wsl --update`, sonra yeniden başlat |
| `Saat farkı` uyarısı | Ayarlar → Saat ve dil → Tarih ve saat → **Şimdi eşitle**; düzelmezse Docker Desktop'ı yeniden başlat |
| `HTTP 451` veya `HTTP 403` | Bölge/IP engeli olabilir. Engel aşma yöntemi deneme, sonucu bana getir |
| Çift tıklayınca pencere hemen kapanıyor | Dosyanın `C:\CyberBot` içinde olduğundan emin ol; olmuyorsa ekran görüntüsü getir |
