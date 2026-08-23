/* ============================================================
   SES EFEKTLERİ
   Dosya kullanmaz; sesleri tarayıcı Web Audio ile üretir.
   Müzik açık ya da kapalı olsun, bağımsız çalışır.
   ============================================================ */

(function () {
  "use strict";

  // BURAYA GENEL SES SEVİYESİNİ AYARLAYABİLİRSİN (0 = sessiz, 1 = en yüksek)
  var GENEL_SES = 0.22;

  var baglam = null;

  // Tarayıcılar, kullanıcı bir şeye dokunmadan ses açmaya izin vermez;
  // bu yüzden bağlamı ilk kullanımda kuruyoruz.
  function ctx() {
    if (!baglam) {
      var Ses = window.AudioContext || window.webkitAudioContext;
      if (!Ses) { return null; }
      try { baglam = new Ses(); } catch (hata) { return null; }
    }
    if (baglam.state === "suspended") { baglam.resume(); }
    return baglam;
  }

  /* --- Tek bir nota --- */
  function ton(ayar) {
    var b = ctx();
    if (!b) { return; }

    var bas = b.currentTime + (ayar.gecikme || 0);
    var sure = ayar.sure || 0.2;

    var salinim = b.createOscillator();
    var kazanc = b.createGain();

    salinim.type = ayar.tur || "sine";
    salinim.frequency.setValueAtTime(ayar.frekans, bas);
    if (ayar.bitisFrekans) {
      salinim.frequency.exponentialRampToValueAtTime(ayar.bitisFrekans, bas + sure);
    }

    var tepe = (ayar.ses || 1) * GENEL_SES;
    kazanc.gain.setValueAtTime(0.0001, bas);
    kazanc.gain.exponentialRampToValueAtTime(tepe, bas + 0.012);
    kazanc.gain.exponentialRampToValueAtTime(0.0001, bas + sure);

    salinim.connect(kazanc).connect(b.destination);
    salinim.start(bas);
    salinim.stop(bas + sure + 0.02);
  }

  /* --- Gürültü (üfleme, hışırtı) --- */
  function gurultu(ayar) {
    var b = ctx();
    if (!b) { return; }

    var bas = b.currentTime + (ayar.gecikme || 0);
    var sure = ayar.sure || 0.25;

    var ornekSayisi = Math.floor(b.sampleRate * sure);
    var tampon = b.createBuffer(1, ornekSayisi, b.sampleRate);
    var veri = tampon.getChannelData(0);
    for (var i = 0; i < ornekSayisi; i++) { veri[i] = Math.random() * 2 - 1; }

    var kaynak = b.createBufferSource();
    kaynak.buffer = tampon;

    var suzgec = b.createBiquadFilter();
    suzgec.type = ayar.suzgecTuru || "lowpass";
    suzgec.frequency.setValueAtTime(ayar.baslangicHz || 1800, bas);
    if (ayar.bitisHz) {
      suzgec.frequency.exponentialRampToValueAtTime(ayar.bitisHz, bas + sure);
    }
    suzgec.Q.value = ayar.q || 1;

    var kazanc = b.createGain();
    var tepe = (ayar.ses || 1) * GENEL_SES;
    kazanc.gain.setValueAtTime(0.0001, bas);
    kazanc.gain.exponentialRampToValueAtTime(tepe, bas + 0.02);
    kazanc.gain.exponentialRampToValueAtTime(0.0001, bas + sure);

    kaynak.connect(suzgec).connect(kazanc).connect(b.destination);
    kaynak.start(bas);
    kaynak.stop(bas + sure + 0.02);
  }

  /* ============================================================
     EFEKTLER
     ============================================================ */

  // Mum üfleme: kısa bir "püf"
  function mumSondur() {
    gurultu({ sure: 0.3, baslangicHz: 2200, bitisHz: 320, ses: 0.85 });
    ton({ frekans: 320, bitisFrekans: 160, sure: 0.18, tur: "sine", ses: 0.25 });
  }

  // Kutlama: yükselen üç nota + hafif bir hışırtı
  function kutlama() {
    var notalar = [523.25, 659.25, 783.99, 1046.5];
    notalar.forEach(function (frekans, sira) {
      ton({
        frekans: frekans,
        sure: 0.42,
        tur: "triangle",
        ses: 0.7,
        gecikme: sira * 0.085
      });
    });
    gurultu({ sure: 0.7, baslangicHz: 6000, bitisHz: 1200, ses: 0.3, gecikme: 0.05 });
  }

  // Zarf açılması: kâğıt hışırtısı, ardından kutlama
  function zarfAc() {
    gurultu({ sure: 0.16, baslangicHz: 3500, bitisHz: 900, ses: 0.5, suzgecTuru: "bandpass", q: 0.7 });
    gurultu({ sure: 0.2, baslangicHz: 2600, bitisHz: 700, ses: 0.42, suzgecTuru: "bandpass", q: 0.7, gecikme: 0.14 });
    setTimeout(kutlama, 260);
  }

  function zarfKapat() {
    gurultu({ sure: 0.18, baslangicHz: 2200, bitisHz: 600, ses: 0.4, suzgecTuru: "bandpass", q: 0.7 });
  }

  // Doğru cevap: yükselen ikili + kutlama
  function dogruCevap() {
    ton({ frekans: 587.33, sure: 0.2, tur: "sine", ses: 0.8 });
    ton({ frekans: 880, sure: 0.35, tur: "sine", ses: 0.8, gecikme: 0.13 });
    setTimeout(kutlama, 320);
  }

  // Yanlış cevap: yumuşak, alçak bir ton
  function yanlisCevap() {
    ton({ frekans: 233.08, bitisFrekans: 174.61, sure: 0.32, tur: "sine", ses: 0.55 });
  }

  // Mesaj gönderildi / not iletildi
  function mesaj() {
    ton({ frekans: 784, sure: 0.11, tur: "sine", ses: 0.6 });
    ton({ frekans: 1174.66, sure: 0.14, tur: "sine", ses: 0.45, gecikme: 0.07 });
  }

  // Mum yeniden yakma: küçük bir kıvılcım
  function mumYak() {
    ton({ frekans: 440, bitisFrekans: 880, sure: 0.16, tur: "triangle", ses: 0.5 });
  }

  window.SesEfekt = {
    mumSondur: mumSondur,
    mumYak: mumYak,
    kutlama: kutlama,
    zarfAc: zarfAc,
    zarfKapat: zarfKapat,
    dogruCevap: dogruCevap,
    yanlisCevap: yanlisCevap,
    mesaj: mesaj
  };
})();
