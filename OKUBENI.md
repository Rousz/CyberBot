# Zara — Doğum Günü Sitesi

Tek sayfalık, tamamen statik bir doğum günü / tanıtım sitesi.
Vanilla HTML5 + CSS3 + vanilla JavaScript. Build aracı, backend, veritabanı yok.

## Dosya yapısı

```
index.html              → tüm bölümler ve metinler
css/style.css           → tema, renkler, animasyonlar, responsive kurallar
js/script.js            → sayaç, mumlar, konfeti, zarf, müzik, scroll animasyonları
assets/audio/song.mp3   → arka plan müziği (dosyayı buraya kendin koyacaksın)
```

## Önizleme

Proje klasöründe `python3 -m http.server` çalıştırıp tarayıcıda
`http://localhost:8000` adresini aç (`index.html` dosyasına çift tıklamak da çalışır).

## Değiştirilecek yerler

| Ne | Nerede |
| --- | --- |
| Doğum tarihi (sayaç) | `js/script.js` en üstteki `DOGUM_TARIHI` sabiti — biçim `"YYYY-AA-GG"` |
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

Varsayılan olarak şarkı **YouTube'un resmî gömülü oynatıcısından** çalıyor; sayfada
görünmez bir oynatıcı var, köşedeki buton onu başlatıp durduruyor. Hiçbir dosya
indirilmiyor, telif açısından sorun yok.

Değiştirmek için `js/script.js` en üstü:

```js
var MUZIK_KAYNAGI  = "youtube";        // "youtube" veya "dosya"
var YOUTUBE_VIDEO_ID = "q2U9uz3k0wY";  // youtube.com/watch?v=BURASI
```

Kendi mp3'ünü kullanmak istersen `MUZIK_KAYNAGI` değerini `"dosya"` yap ve dosyayı
`assets/audio/song.mp3` olarak koy.

Not: YouTube tarafında videonun gömülmesi kapatılmışsa (yükleyenin tercihi) o video
sitede çalmaz; böyle bir durumda buton sessizce hiçbir şey yapar, başka bir video
kimliği denemek gerekir.

## Notlar

- Müzik kaynağına erişilemezse site yine sorunsuz çalışır: play butonu sessizce hiçbir şey yapmaz.
- Autoplay yok (tarayıcılar engelliyor); müzik ancak butona basılınca başlar.
- `prefers-reduced-motion` açık olan cihazlarda animasyonlar kendiliğinden kapanır.
