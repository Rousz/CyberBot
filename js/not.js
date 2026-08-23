/* ============================================================
   YAPIMCIYA NOT + ZARA SOHBETİ
   Firebase (Firestore + anonim giriş) ile çalışır.
   Ayarlar js/firebase-ayar.js içinde.
   ============================================================ */

import { FIREBASE_AYAR, AYAR_HAZIR } from "./firebase-ayar.js";

/* --- Güvenlik sorusunun cevabı --- */
// BURAYA CEVABI DEĞİŞTİREBİLİRSİN
const DOGRU_CEVAP_BASLANGIC = "et";

// BURAYA DOĞRU CEVAP VERİLİNCE ÇIKACAK BÜYÜK MESAJI YAZ
const BUYUK_MESAJ = "Aferim kiz soru basitti ama tek sen dogru cevap verirdin, gel yazisak.";

const SAKLAMA_ANAHTARI = "zara_sohbet_kimlik";
// Not: kilit bilerek hatırlanmıyor — soru her sayfa yenilemesinde tekrar sorulur.
const ESKI_KILIT_ANAHTARI = "zara_kilit_acik";

/* --- Kısa yollar --- */
const sec = (s) => document.querySelector(s);
const tumu = (s) => Array.prototype.slice.call(document.querySelectorAll(s));

/* --- Türkçe duyarlı sadeleştirme --- */
function sadelestir(metin) {
  return (metin || "")
    .toLocaleLowerCase("tr-TR")
    .replace(/ı/g, "i").replace(/ş/g, "s").replace(/ğ/g, "g")
    .replace(/ü/g, "u").replace(/ö/g, "o").replace(/ç/g, "c")
    .replace(/[^a-z]/g, "");
}

function cevapDogruMu(girilen) {
  const s = sadelestir(girilen);
  // "et", "eti", "et yemekleri" gibi cevapları kabul eder
  return s.startsWith(DOGRU_CEVAP_BASLANGIC) && s.length <= 14;
}

/* --- Arayüz öğeleri --- */
const bolum = sec("#notBolum");
const secimAlani = sec("#notSecim");
const zaraDugme = sec("#zaraDugme");
const notDugme = sec("#notAcDugme");

const soruAlani = sec("#soruAlani");
const soruForm = sec("#soruForm");
const soruGirdi = sec("#soruGirdi");
const soruUyari = sec("#soruUyari");

const notAlani = sec("#notAlani");
const notForm = sec("#notForm");
const notAd = sec("#notAd");
const notMetin = sec("#notMetin");
const notDurum = sec("#notDurum");

const sohbetAlani = sec("#sohbetAlani");
const sohbetListe = sec("#sohbetListe");
const sohbetForm = sec("#sohbetForm");
const sohbetGirdi = sec("#sohbetGirdi");

const kisayol = sec("#notKisayol");
const perde = sec("#buyukMesajPerde");
const perdeMetin = sec("#buyukMesajMetin");
const perdeKapat = sec("#buyukMesajKapat");

const hazirlaniyorNot = sec("#notHazirlaniyor");

/* --- Görünüm yardımcıları --- */
function goster(el) { if (el) el.hidden = false; }
function gizle(el) { if (el) el.hidden = true; }

function paneliAc(hedef) {
  [secimAlani, soruAlani, notAlani, sohbetAlani].forEach(gizle);
  goster(hedef);
}

/* ============================================================
   AYARLAR YOKSA: bölüm "hazırlanıyor" durumunda kalsın
   ============================================================ */
if (!AYAR_HAZIR) {
  if (bolum) {
    gizle(secimAlani);
    goster(hazirlaniyorNot);
  }
} else {
  baslat();
}

/* ============================================================
   FIREBASE
   ============================================================ */
async function baslat() {
  const { initializeApp } = await import("https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js");
  const { getAuth, signInAnonymously, onAuthStateChanged } =
    await import("https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js");
  const {
    getFirestore, collection, addDoc, doc, getDoc, setDoc,
    query, orderBy, onSnapshot, serverTimestamp
  } = await import("https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js");

  const uygulama = initializeApp(FIREBASE_AYAR);
  const kimlik = getAuth(uygulama);
  const vt = getFirestore(uygulama);

  let kullaniciId = null;

  try {
    await signInAnonymously(kimlik);
  } catch (hata) {
    // Anonim giriş kapalıysa bölümü sessizce hazırlanıyor durumunda bırak
    gizle(secimAlani);
    goster(hazirlaniyorNot);
    return;
  }

  onAuthStateChanged(kimlik, (kullanici) => {
    if (kullanici) {
      kullaniciId = kullanici.uid;
      araYuzuKur();
    }
  });

  /* --- Arayüz --- */
  function araYuzuKur() {
    gizle(hazirlaniyorNot);
    goster(secimAlani);
    // Eski sürümden kalan kilit varsa temizle: soru her açılışta sorulmalı
    localStorage.removeItem(ESKI_KILIT_ANAHTARI);
  }

  /* --- Zara kapısı --- */
  if (zaraDugme) {
    zaraDugme.addEventListener("click", () => {
      // Sohbet geçmişi dursa bile soru her seferinde sorulur
      paneliAc(soruAlani);
      if (soruGirdi) { soruGirdi.value = ""; soruGirdi.focus(); }
      if (soruUyari) soruUyari.hidden = true;
    });
  }

  if (soruForm) {
    soruForm.addEventListener("submit", async (olay) => {
      olay.preventDefault();
      if (!cevapDogruMu(soruGirdi.value)) {
        if (window.SesEfekt) { window.SesEfekt.yanlisCevap(); }
        soruUyari.textContent = "Olmadı. Bir daha düşün.";
        soruUyari.hidden = false;
        soruGirdi.select();
        return;
      }
      soruUyari.hidden = true;
      if (window.SesEfekt) { window.SesEfekt.dogruCevap(); }
      await sohbetOdasiHazirla();
      buyukMesajiGoster();
    });
  }

  async function sohbetOdasiHazirla() {
    let id = localStorage.getItem(SAKLAMA_ANAHTARI);
    if (id) {
      const belge = await getDoc(doc(vt, "sohbetler", id));
      if (belge.exists()) return id;
    }
    const yeni = doc(collection(vt, "sohbetler"));
    await setDoc(yeni, {
      sahip: kullaniciId,
      baslik: "Zara",
      olusturma: serverTimestamp(),
      sonTarih: serverTimestamp(),
      sonMesaj: "(sohbet açıldı)"
    });
    localStorage.setItem(SAKLAMA_ANAHTARI, yeni.id);
    return yeni.id;
  }

  /* --- Sohbet --- */
  let dinleyiciKapat = null;

  async function sohbetiBaslat(id) {
    paneliAc(sohbetAlani);
    if (dinleyiciKapat) dinleyiciKapat();

    const mesajlar = query(
      collection(vt, "sohbetler", id, "mesajlar"),
      orderBy("tarih", "asc")
    );

    let oncekiSayi = -1;

    dinleyiciKapat = onSnapshot(mesajlar, (anlik) => {
      // Yapımcıdan yeni mesaj geldiyse ve bölüm ekranda değilse kısayolu işaretle
      let sonKim = null;
      anlik.forEach((b) => { sonKim = b.data().kim; });
      if (oncekiSayi >= 0 && anlik.size > oncekiSayi && sonKim === "yapimci") {
        yeniMesajIsareti();
      }
      oncekiSayi = anlik.size;

      sohbetListe.innerHTML = "";
      if (anlik.empty) {
        const bos = document.createElement("p");
        bos.className = "sohbet__bos";
        bos.textContent = "Burası şimdilik boş. İlk mesajı yazabilirsin.";
        sohbetListe.appendChild(bos);
      }
      anlik.forEach((belge) => {
        const veri = belge.data();
        const balon = document.createElement("div");
        balon.className = "balon " + (veri.kim === "yapimci" ? "balon--yapimci" : "balon--zara");
        balon.textContent = veri.metin;
        sohbetListe.appendChild(balon);
      });
      sohbetListe.scrollTop = sohbetListe.scrollHeight;
    }, () => {
      // okuma izni yoksa sessizce geç
    });

    if (sohbetForm && !sohbetForm.dataset.bagli) {
      sohbetForm.dataset.bagli = "1";
      sohbetForm.addEventListener("submit", async (olay) => {
        olay.preventDefault();
        const metin = sohbetGirdi.value.trim();
        if (!metin) return;
        sohbetGirdi.value = "";
        if (window.SesEfekt) { window.SesEfekt.mesaj(); }
        const odaId = localStorage.getItem(SAKLAMA_ANAHTARI);
        await addDoc(collection(vt, "sohbetler", odaId, "mesajlar"), {
          kim: "zara",
          metin: metin,
          tarih: serverTimestamp()
        });
        await setDoc(doc(vt, "sohbetler", odaId), {
          sahip: kullaniciId,
          sonMesaj: metin.slice(0, 80),
          sonTarih: serverTimestamp(),
          sonYazan: "zara",
          yapimciOkudu: false
        }, { merge: true });
      });
    }
  }

  /* --- "Yeni mesaj" rozeti --- */

  function bolumEkrandaMi() {
    if (!bolum) return false;
    const k = bolum.getBoundingClientRect();
    return k.top < window.innerHeight * 0.75 && k.bottom > 0;
  }

  function yeniMesajIsareti() {
    if (!kisayol || bolumEkrandaMi()) return;
    kisayol.classList.add("not-kisayol--yeni");
    const uzun = kisayol.querySelector(".not-kisayol__uzun");
    const kisa = kisayol.querySelector(".not-kisayol__kisa");
    if (uzun) uzun.textContent = "yapımcı cevap yazdı";
    if (kisa) kisa.textContent = "yeni mesaj";
  }

  function isaretiTemizle() {
    if (!kisayol || !kisayol.classList.contains("not-kisayol--yeni")) return;
    kisayol.classList.remove("not-kisayol--yeni");
    const uzun = kisayol.querySelector(".not-kisayol__uzun");
    const kisa = kisayol.querySelector(".not-kisayol__kisa");
    if (uzun) uzun.textContent = "yapımcıya not bırak";
    if (kisa) kisa.textContent = "not bırak";
  }

  if (bolum && "IntersectionObserver" in window) {
    new IntersectionObserver((kayitlar) => {
      kayitlar.forEach((k) => { if (k.isIntersecting) isaretiTemizle(); });
    }, { threshold: 0.25 }).observe(bolum);
  }

  /* --- Herkese açık not --- */
  if (notDugme) {
    notDugme.addEventListener("click", () => {
      paneliAc(notAlani);
      if (notMetin) notMetin.focus();
    });
  }

  if (notForm) {
    notForm.addEventListener("submit", async (olay) => {
      olay.preventDefault();
      const metin = notMetin.value.trim();
      if (!metin) return;

      const dugme = notForm.querySelector("button[type=submit]");
      if (dugme) dugme.disabled = true;

      try {
        await addDoc(collection(vt, "notlar"), {
          ad: notAd.value.trim() || "isimsiz",
          mesaj: metin,
          tarih: serverTimestamp(),
          okundu: false
        });
        notForm.hidden = true;
        notDurum.hidden = false;
        if (window.SesEfekt) { window.SesEfekt.mesaj(); }
      } catch (hata) {
        notDurum.textContent = "Not gönderilemedi, birazdan tekrar dene.";
        notDurum.hidden = false;
        if (dugme) dugme.disabled = false;
      }
    });
  }

  /* --- Büyük mesaj perdesi --- */
  function buyukMesajiGoster() {
    if (!perde) return;
    perdeMetin.textContent = BUYUK_MESAJ;
    perde.hidden = false;
    document.body.style.overflow = "hidden";
    if (typeof window.konfetiPatlat === "function") window.konfetiPatlat(120);
  }

  if (perdeKapat) {
    perdeKapat.addEventListener("click", async () => {
      perde.hidden = true;
      document.body.style.overflow = "";
      const id = await sohbetOdasiHazirla();
      sohbetiBaslat(id);
      bolum.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  /* --- Geri butonları --- */
  tumu("[data-geri]").forEach((dugme) => {
    dugme.addEventListener("click", () => paneliAc(secimAlani));
  });
}
