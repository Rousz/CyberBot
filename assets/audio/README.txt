BU KLASÖRE MÜZİK DOSYASINI KOY
==============================

Sayfadaki arka plan müziği şu dosyayı arıyor:

    assets/audio/song.mp3

Kendi mp3 dosyanı bu klasöre "song.mp3" adıyla kopyalaman yeterli;
başka hiçbir yeri değiştirmene gerek yok.

Dosya burada yokken de site sorunsuz çalışır: köşedeki play butonuna
basıldığında hiçbir hata çıkmaz, buton sessizce eski hâline döner.

Başka bir dosya adı/uzantısı kullanmak istersen, index.html içindeki
şu satırı güncelle:

    <audio id="arkaMuzik" src="assets/audio/song.mp3" loop preload="none"></audio>
