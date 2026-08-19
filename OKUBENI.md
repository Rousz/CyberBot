# Zara — Doğum Günü Sitesi

Tek sayfalık, tamamen statik bir doğum günü / tanıtım sitesi.
Vanilla HTML5 + CSS3 + vanilla JavaScript. Build aracı, backend, veritabanı yok.

## Dosya yapısı

```
index.html                 → 9 bölümün tamamı ve tüm metinler
css/style.css              → tema, renkler, animasyonlar, responsive kurallar
js/script.js               → sayaç, mumlar, konfeti, zarf, müzik, scroll animasyonları
assets/audio/song.mp3      → yerel müzik seçeneği (sadece "dosya" modunda gerekir)
```

Bölümler: kapak → kayan şerit → 01 Onu Özel Yapan Küçük Şeyler → 02 Neden Şanslıyız →
03 Dünyanın En Güzel Gülüşü → 04 Çocukluk Köşesi → 05 Zamanın Damgası →
06 Zaman Çizelgesi → 07 Hollywood'dan Gizemli Bir Tebrik → 08 Mumları Üflemek Kaldı →
09 Mühürlü Köşe

## Önizleme

Proje klasöründe `python3 -m http.server` çalıştırıp tarayıcıda
`http://localhost:8000` adresini aç (`index.html` dosyasına çift tıklamak da çalışır).

## Değiştirilecek yerler

| Ne | Nerede |
| --- | --- |
| Doğum tarihi (sayaç + kapak rozeti) | `js/script.js` en üstteki `DOGUM_TARIHI` sabiti — biçim `"YYYY-AA-GG"` |
| Hollywood avatarı | `index.html` içindeki `id="mektupAvatar"` görselinin `src` adresi (şu an imgur) |
| Kayan şeritteki sözler | `index.html` içinde `<!-- BURAYA ŞERİTTE DÖNECEK SÖZLERİ YAZ -->` — **iki kopyayı da** güncelle (döngü için ikisi aynı olmalı) |
| Doğum saati (isteğe bağlı) | `js/script.js` içindeki `DOGUM_SAATI` sabiti |
| Anı metinleri | `index.html` içinde `<!-- BURAYA ANI METNİNİ YAZ -->` yorumlarının olduğu 5 kart |
| Gizli/mühürlü not | `index.html` içinde `<!-- BURAYA EN KİŞİSEL, EN İÇTEN NOTU YAZ -->` |
| Fotoğraf alt yazıları | `<!-- BURAYA ... ALT YAZISINI YAZ -->` yorumları |
| Mumlar sönünce çıkan mesaj | `js/script.js` içindeki `KUTLAMA_MESAJI` |
| Müzik (YouTube) | `js/script.js` içindeki `YOUTUBE_VIDEO_ID` — linkteki `v=` değeri |
| Müzik (yerel dosya) | `js/script.js` içinde `MUZIK_KAYNAGI = "dosya"` yap, mp3'ü `assets/audio/song.mp3` olarak koy |
| Renkler | `css/style.css` en üstteki `:root { --krem, --toz-pembe, --adacayi ... }` |

`index.html` içindeki tüm düzenlenebilir yerler büyük harfli Türkçe
`<!-- BURAYA ... -->` yorumlarıyla işaretli; dosyada bu kelimeyi aratmak yeterli.

## Yayına alma

`index.html`, `css/`, `js/` ve `assets/` klasörlerini olduğu gibi domainin kök
dizinine yükle. Derleme adımı gerekmiyor.

Fotoğraflar imgur üzerinden, yazı tipleri (Caveat + Lora) Google Fonts üzerinden
yükleniyor; yerel dosya indirmeye gerek yok.

## Müzik nasıl çalışıyor?

Şu anki ayar: şarkı **`assets/audio/song.mp3` dosyasından** çalıyor. Köşedeki buton
başlatıp durduruyor, parça bitince başa dönüyor (döngü), ses seviyesi %55.

Alternatif olarak YouTube'un resmî gömülü oynatıcısı da hazır duruyor; `MUZIK_KAYNAGI`
değerini `"youtube"` yapman yeterli.

Değiştirmek için `js/script.js` en üstü:

```js
var MUZIK_KAYNAGI  = "dosya";          // "dosya" veya "youtube"
var YOUTUBE_VIDEO_ID = "q2U9uz3k0wY";  // youtube.com/watch?v=BURASI
```

Şarkıyı değiştirmek için yeni mp3'ü `assets/audio/song.mp3` olarak kaydetmen yeterli.

Not: YouTube tarafında videonun gömülmesi kapatılmışsa (yükleyenin tercihi) o video
sitede çalmaz; böyle bir durumda buton sessizce hiçbir şey yapar, başka bir video
kimliği denemek gerekir.

## Notlar

- Müzik kaynağına erişilemezse site yine sorunsuz çalışır: play butonu sessizce hiçbir şey yapmaz.
- Autoplay yok (tarayıcılar engelliyor); müzik ancak butona basılınca başlar.
- `prefers-reduced-motion` açık olan cihazlarda animasyonlar kendiliğinden kapanır.
