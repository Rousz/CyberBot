/* ============================================================
   ZARA — SAYFA ETKİLEŞİMLERİ
   Vanilla JavaScript. Hiçbir kütüphane gerekmez.
   ============================================================ */

(function () {
  "use strict";

  /* ------------------------------------------------------------
     ⚙️ AYARLAR — BURAYI DÜZENLE
     ------------------------------------------------------------ */

  // BURAYA ZARA'NIN DOĞUM TARİHİNİ YAZ (biçim: "YYYY-AA-GG")
  var DOGUM_TARIHI = "2005-08-14";

  // BURAYA DOĞUM SAATİNİ YAZABİLİRSİN (bilinmiyorsa "00:00" kalabilir)
  var DOGUM_SAATI = "00:00";

  // MÜZİK KAYNAĞI: "youtube"  → şarkı YouTube'dan çalar (dosya indirmeye gerek yok)
  //                "dosya"    → assets/audio/song.mp3 dosyasını çalar
  var MUZIK_KAYNAGI = "youtube";

  // YouTube video kimliği (linkteki v= değeri). Şu anki: q2U9uz3k0wY
  var YOUTUBE_VIDEO_ID = "q2U9uz3k0wY";

  /* ------------------------------------------------------------
     Yardımcılar
     ------------------------------------------------------------ */

  var AYLAR_KISA = [
    "oca", "şub", "mar", "nis", "may", "haz",
    "tem", "ağu", "eyl", "eki", "kas", "ara"
  ];

  var AYLAR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
  ];

  var azHareket = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

  function sec(secici) { return document.querySelector(secici); }
  function tumu(secici) { return Array.prototype.slice.call(document.querySelectorAll(secici)); }

  function sayiYaz(element, deger) {
    if (element) { element.textContent = String(deger); }
  }

  /* ------------------------------------------------------------
     1) KAPAK — parallax
     ------------------------------------------------------------ */

  var kapakMedya = sec("#kapakMedya");
  var beklemede = false;

  function parallaxCiz() {
    beklemede = false;
    if (!kapakMedya) { return; }
    var kaydirma = window.pageYOffset || document.documentElement.scrollTop || 0;
    // Kapak ekrandan çıkınca hesap yapmayı bırak
    if (kaydirma > window.innerHeight * 1.2) { return; }
    kapakMedya.style.transform = "translate3d(0, " + (kaydirma * 0.32) + "px, 0)";
  }

  function parallaxIste() {
    if (beklemede) { return; }
    beklemede = true;
    window.requestAnimationFrame(parallaxCiz);
  }

  if (kapakMedya && !azHareket) {
    window.addEventListener("scroll", parallaxIste, { passive: true });
    parallaxCiz();
  }

  /* ------------------------------------------------------------
     2) SCROLL İLE BELİRME (IntersectionObserver)
     ------------------------------------------------------------ */

  var belirenler = tumu(".reveal");

  if ("IntersectionObserver" in window && !azHareket) {
    var gozlemci = new IntersectionObserver(function (kayitlar) {
      kayitlar.forEach(function (kayit) {
        if (kayit.isIntersecting) {
          kayit.target.classList.add("gorunur");
          gozlemci.unobserve(kayit.target);
        }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });

    belirenler.forEach(function (oge, sira) {
      oge.style.transitionDelay = (Math.min(sira % 4, 3) * 0.09) + "s";
      gozlemci.observe(oge);
    });
  } else {
    // Destek yoksa her şey doğrudan görünür olsun
    belirenler.forEach(function (oge) { oge.classList.add("gorunur"); });
  }

  /* ------------------------------------------------------------
     3) YAŞ / GÜN SAYACI
     ------------------------------------------------------------ */

  var dogum = new Date(DOGUM_TARIHI + "T" + DOGUM_SAATI + ":00");
  var dogumGecerli = !isNaN(dogum.getTime());

  var gunEl = sec("#gunSayisi");
  var yasEl = sec("#yasSayisi");
  var saatEl = sec("#saatSayisi");
  var dakikaEl = sec("#dakikaSayisi");
  var saniyeEl = sec("#saniyeSayisi");
  var dipnotEl = sec("#sayacDipnot");
  var rozetGunEl = sec("#rozetGun");
  var rozetAyEl = sec("#rozetAy");
  var kapakUstYaziEl = sec("#kapakUstYazi");

  function yasHesapla(baslangic, simdi) {
    var yas = simdi.getFullYear() - baslangic.getFullYear();
    var ayFarki = simdi.getMonth() - baslangic.getMonth();
    if (ayFarki < 0 || (ayFarki === 0 && simdi.getDate() < baslangic.getDate())) {
      yas -= 1;
    }
    return yas < 0 ? 0 : yas;
  }

  function sayaciGuncelle() {
    if (!dogumGecerli) { return; }

    var simdi = new Date();
    var fark = simdi.getTime() - dogum.getTime();
    if (fark < 0) { fark = 0; }

    var saniye = Math.floor(fark / 1000);
    var gun = Math.floor(saniye / 86400);
    var kalan = saniye % 86400;

    sayiYaz(gunEl, gun.toLocaleString("tr-TR"));
    sayiYaz(yasEl, yasHesapla(dogum, simdi));
    sayiYaz(saatEl, Math.floor(kalan / 3600));
    sayiYaz(dakikaEl, Math.floor((kalan % 3600) / 60));
    sayiYaz(saniyeEl, kalan % 60);
  }

  if (dogumGecerli) {
    // Kapaktaki rozet ve üst yazı da doğum tarihinden geliyor
    if (rozetGunEl) { rozetGunEl.textContent = dogum.getDate(); }
    if (rozetAyEl) { rozetAyEl.textContent = AYLAR_KISA[dogum.getMonth()]; }
    if (kapakUstYaziEl) {
      kapakUstYaziEl.textContent =
        "bir doğum günü hikâyesi — " + dogum.getDate() + " " +
        AYLAR[dogum.getMonth()].toLocaleLowerCase("tr-TR");
    }

    if (dipnotEl) {
      var bugun = new Date();
      var dogumGunuMu =
        bugun.getDate() === dogum.getDate() && bugun.getMonth() === dogum.getMonth();

      // BURAYA SAYAÇ ALTINDAKİ CÜMLEYİ YAZABİLİRSİN
      dipnotEl.textContent = dogumGunuMu
        ? "ve bugün, o günün yıl dönümü."
        : "her biri, dünyanın onunla birlikte geçirdiği bir gün.";
    }

    sayaciGuncelle();
    window.setInterval(sayaciGuncelle, 1000);
  } else if (dipnotEl) {
    dipnotEl.textContent = "sayaç için doğum tarihi henüz girilmedi.";
  }

  /* ------------------------------------------------------------
     4) KONFETİ
     ------------------------------------------------------------ */

  var konfetiAlan = sec("#konfetiAlan");
  var KONFETI_RENKLERI = ["#e3b7ae", "#c9a882", "#a8b89a", "#6b543f", "#f3ddc7", "#c98d84"];

  function konfetiPatlat(adet) {
    if (!konfetiAlan || azHareket) { return; }
    var toplam = adet || 70;

    for (var i = 0; i < toplam; i++) {
      var parca = document.createElement("span");
      parca.className = "konfeti";
      parca.style.left = (Math.random() * 100) + "vw";
      parca.style.background = KONFETI_RENKLERI[Math.floor(Math.random() * KONFETI_RENKLERI.length)];
      parca.style.animationDuration = (2.6 + Math.random() * 2.4) + "s";
      parca.style.animationDelay = (Math.random() * 0.9) + "s";
      parca.style.width = (6 + Math.random() * 7) + "px";
      parca.style.height = (10 + Math.random() * 9) + "px";
      if (Math.random() > 0.6) { parca.style.borderRadius = "50%"; }

      parca.addEventListener("animationend", function () {
        if (this.parentNode) { this.parentNode.removeChild(this); }
      });

      konfetiAlan.appendChild(parca);
    }
  }

  /* ------------------------------------------------------------
     5) MUM ÜFLEME
     ------------------------------------------------------------ */

  var mumlar = tumu(".mum");
  var pastaMesaj = sec("#pastaMesaj");
  var yenidenYakDugme = sec("#mumlariYak");

  // BURAYA MUMLAR SÖNÜNCE ÇIKACAK MESAJI YAZ
  var KUTLAMA_MESAJI = "Bütün mumlar söndü. Dilek tutuldu, kayda geçti.";

  function sonukMumSayisi() {
    return mumlar.filter(function (mum) { return mum.classList.contains("sonuk"); }).length;
  }

  function mumaTiklandi(olay) {
    var mum = olay.currentTarget;
    if (mum.classList.contains("sonuk")) { return; }

    mum.classList.add("sonuk");
    mum.setAttribute("aria-pressed", "true");

    if (sonukMumSayisi() === mumlar.length) {
      if (pastaMesaj) {
        pastaMesaj.textContent = KUTLAMA_MESAJI;
        pastaMesaj.classList.add("gorunur");
      }
      konfetiPatlat(90);
      if (yenidenYakDugme) { yenidenYakDugme.hidden = false; }
    }
  }

  mumlar.forEach(function (mum) {
    mum.addEventListener("click", mumaTiklandi);
  });

  if (yenidenYakDugme) {
    yenidenYakDugme.addEventListener("click", function () {
      mumlar.forEach(function (mum) {
        mum.classList.remove("sonuk");
        mum.setAttribute("aria-pressed", "false");
      });
      if (pastaMesaj) {
        pastaMesaj.classList.remove("gorunur");
        pastaMesaj.textContent = "";
      }
      yenidenYakDugme.hidden = true;
    });
  }

  /* ------------------------------------------------------------
     6) GİZLİ KÖŞE — ZARF
     ------------------------------------------------------------ */

  var zarf = sec("#zarf");
  var zarfDugme = sec("#zarfDugme");
  var zarfYazi = zarfDugme ? zarfDugme.querySelector(".zarf__yazi") : null;

  if (zarf && zarfDugme) {
    zarfDugme.addEventListener("click", function () {
      var acildi = zarf.classList.toggle("acik");
      zarfDugme.setAttribute("aria-expanded", acildi ? "true" : "false");
      if (zarfYazi) { zarfYazi.textContent = acildi ? "Zarfı kapat" : "Zarfı aç"; }
      if (acildi) { konfetiPatlat(24); }
    });
  }

  /* ------------------------------------------------------------
     7) MEKTUP AVATARI
     Fotoğraf (assets/img/tom-hardy.jpg) yoksa yerine baş harf gelir.
     ------------------------------------------------------------ */

  var avatarFoto = sec("#mektupAvatar");
  var avatarHarf = sec("#avatarHarf");

  function avatarYedegeGec() {
    if (avatarFoto) { avatarFoto.style.display = "none"; }
    if (avatarHarf) { avatarHarf.hidden = false; }
  }

  if (avatarFoto) {
    avatarFoto.addEventListener("error", avatarYedegeGec);
    if (avatarFoto.complete && avatarFoto.naturalWidth === 0) { avatarYedegeGec(); }
  }

  /* ------------------------------------------------------------
     8) ARKA PLAN MÜZİĞİ
     İki kaynak destekli (yukarıdaki MUZIK_KAYNAGI sabiti seçer):
       "youtube" → YouTube'un resmî gömülü oynatıcısı (görünmez)
       "dosya"   → assets/audio/song.mp3
     Her iki durumda da bir sorun olursa buton sessizce eski hâline döner.
     ------------------------------------------------------------ */

  var muzik = sec("#arkaMuzik");
  var muzikDugme = sec("#muzikDugme");
  var muzikIkon = sec("#muzikIkon");
  var muzikIpucu = sec("#muzikIpucu");
  var youtubeModu = MUZIK_KAYNAGI === "youtube";

  function muzikDurumu(caliyor) {
    if (muzikIkon) { muzikIkon.textContent = caliyor ? "🔊" : "🔇"; }
    if (muzikDugme) {
      muzikDugme.classList.toggle("caliyor", caliyor);
      muzikDugme.setAttribute("aria-pressed", caliyor ? "true" : "false");
      muzikDugme.setAttribute(
        "aria-label",
        caliyor ? "Arka plan müziğini duraklat" : "Arka plan müziğini çal"
      );
    }
  }

  /* --- YouTube tarafı --- */

  var ytOynatici = null;   // YT.Player nesnesi
  var ytIsteniyor = false; // kullanıcı bekliyor mu
  var ytYukleniyor = false;

  function ytApiYukle() {
    if (ytYukleniyor || window.YT) { return; }
    ytYukleniyor = true;

    var betik = document.createElement("script");
    betik.src = "https://www.youtube.com/iframe_api";
    betik.async = true;
    betik.onerror = function () {
      // İnternet yok ya da engellenmiş — sessizce vazgeç
      ytYukleniyor = false;
      ytIsteniyor = false;
      muzikDurumu(false);
    };
    document.head.appendChild(betik);
  }

  // YouTube API hazır olunca bu global fonksiyonu kendisi çağırır
  window.onYouTubeIframeAPIReady = function () {
    if (!document.getElementById("ytOynatici")) { return; }

    ytOynatici = new YT.Player("ytOynatici", {
      videoId: YOUTUBE_VIDEO_ID,
      playerVars: {
        autoplay: 0,
        controls: 0,
        disablekb: 1,
        loop: 1,
        playlist: YOUTUBE_VIDEO_ID, // loop'un çalışması için gerekli
        modestbranding: 1,
        playsinline: 1,
        rel: 0
      },
      events: {
        onReady: function (olay) {
          olay.target.setVolume(55);
          if (ytIsteniyor) { olay.target.playVideo(); }
        },
        onStateChange: function (olay) {
          if (olay.data === YT.PlayerState.PLAYING) {
            muzikDurumu(true);
          } else if (olay.data === YT.PlayerState.PAUSED || olay.data === YT.PlayerState.ENDED) {
            muzikDurumu(false);
          }
        },
        onError: function () {
          // Video gömülemiyor / kaldırılmış olabilir
          ytIsteniyor = false;
          muzikDurumu(false);
        }
      }
    });
  };

  function youtubeAcKapa() {
    if (!ytOynatici || typeof ytOynatici.getPlayerState !== "function") {
      // Oynatıcı henüz kurulmadı: API'yi yükle, hazır olunca kendiliğinden başlasın
      ytIsteniyor = true;
      ytApiYukle();
      return;
    }

    var durum = ytOynatici.getPlayerState();
    if (durum === 1 || durum === 3) { // 1: çalıyor, 3: yükleniyor
      ytOynatici.pauseVideo();
      muzikDurumu(false);
    } else {
      ytOynatici.playVideo();
    }
  }

  /* --- Yerel mp3 tarafı --- */

  function dosyaAcKapa() {
    if (!muzik) { return; }

    if (muzik.paused) {
      var sozVerilen = muzik.play();
      if (sozVerilen && typeof sozVerilen.then === "function") {
        sozVerilen.then(function () {
          muzikDurumu(true);
        }).catch(function () {
          // Dosya yok ya da tarayıcı izin vermedi — sessizce eski hâline dön
          muzikDurumu(false);
        });
      } else {
        muzikDurumu(true);
      }
    } else {
      muzik.pause();
      muzikDurumu(false);
    }
  }

  if (muzikDugme) {
    if (muzik) { muzik.volume = 0.55; }

    muzikDugme.addEventListener("click", function () {
      if (muzikIpucu) { muzikIpucu.classList.add("gizle"); }
      if (youtubeModu) { youtubeAcKapa(); } else { dosyaAcKapa(); }
    });

    if (muzik && !youtubeModu) {
      muzik.addEventListener("error", function () { muzikDurumu(false); });
      muzik.addEventListener("ended", function () { muzikDurumu(false); });
      muzik.addEventListener("pause", function () { muzikDurumu(false); });
      muzik.addEventListener("play", function () { muzikDurumu(true); });
    }
  }
})();
