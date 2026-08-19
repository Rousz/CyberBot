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
| Müzik | `assets/audio/song.mp3` — mp3 dosyanı bu adla bu klasöre kopyala |
| Renkler | `css/style.css` en üstteki `:root { --krem, --toz-pembe, --adacayi ... }` |

`index.html` içindeki tüm düzenlenebilir yerler büyük harfli Türkçe
`<!-- BURAYA ... -->` yorumlarıyla işaretli; dosyada bu kelimeyi aratmak yeterli.

## Yayına alma

`index.html`, `css/`, `js/` ve `assets/` klasörlerini olduğu gibi domainin kök
dizinine yükle. Derleme adımı gerekmiyor.

Fotoğraflar imgur üzerinden, yazı tipleri (Caveat + Lora) Google Fonts üzerinden
yükleniyor; yerel dosya indirmeye gerek yok.

## Notlar

- Müzik dosyası yokken de site sorunsuz çalışır: play butonu sessizce hiçbir şey yapmaz.
- Autoplay yok (tarayıcılar engelliyor); müzik ancak butona basılınca başlar.
- `prefers-reduced-motion` açık olan cihazlarda animasyonlar kendiliğinden kapanır.
