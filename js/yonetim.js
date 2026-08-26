/* ============================================================
   YÖNETİM PANELİ
   Notları okur, sohbetlere cevap verir.
   Sadece firebase-ayar.js içindeki YONETICI_EPOSTA girebilir.
   ============================================================ */

import { FIREBASE_AYAR, YONETICI_EPOSTA, AYAR_HAZIR } from "./firebase-ayar.js";

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import {
  getFirestore, collection, doc, addDoc, setDoc, updateDoc, deleteDoc,
  query, orderBy, onSnapshot, serverTimestamp
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";

const sec = (s) => document.querySelector(s);
const tumu = (s) => Array.prototype.slice.call(document.querySelectorAll(s));

const girisEkrani = sec("#girisEkrani");
const panelEkrani = sec("#panelEkrani");
const girisForm = sec("#girisForm");
const girisUyari = sec("#girisUyari");

if (!AYAR_HAZIR) {
  girisUyari.textContent = "Firebase ayarları henüz girilmemiş (js/firebase-ayar.js).";
  girisUyari.hidden = false;
  girisForm.querySelector("button").disabled = true;
} else {
  calistir();
}

let notOkunmamis = 0;
let sohbetOkunmamis = 0;
let oncekiOkunmamis = -1;

function basligiGuncelle() {
  const toplam = notOkunmamis + sohbetOkunmamis;
  document.title = toplam > 0 ? "(" + toplam + ") Yönetim" : "Yönetim";
}

function bildirimIzniIste() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function bildirimGoster() {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return; // sekme zaten açıksa rahatsız etme
  try {
    new Notification("Zara yazdı", { body: "Yönetim panelinde yeni mesaj var." });
  } catch (hata) {
    // bildirim engellenmişse sessizce geç
  }
}

function tarihYaz(damga) {
  if (!damga || typeof damga.toDate !== "function") return "";
  const t = damga.toDate();
  return t.toLocaleString("tr-TR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit"
  });
}

function calistir() {
  const uygulama = initializeApp(FIREBASE_AYAR);
  const kimlik = getAuth(uygulama);
  const vt = getFirestore(uygulama);

  let acikSohbetId = null;
  let mesajDinleyici = null;

  /* --- Giriş --- */
  girisForm.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    girisUyari.hidden = true;
    const dugme = girisForm.querySelector("button");
    dugme.disabled = true;
    try {
      await signInWithEmailAndPassword(kimlik, sec("#eposta").value.trim(), sec("#sifre").value);
    } catch (hata) {
      girisUyari.textContent = "Giriş yapılamadı. E-posta ya da şifre hatalı.";
      girisUyari.hidden = false;
    } finally {
      dugme.disabled = false;
    }
  });

  sec("#cikisDugme").addEventListener("click", () => signOut(kimlik));

  onAuthStateChanged(kimlik, (kullanici) => {
    const yetkili = kullanici && (!YONETICI_EPOSTA || kullanici.email === YONETICI_EPOSTA);
    if (yetkili) {
      girisEkrani.hidden = true;
      panelEkrani.hidden = false;
      bildirimIzniIste();
      notlariDinle();
      sohbetleriDinle();
    } else {
      if (kullanici) {
        signOut(kimlik);
        girisUyari.textContent = "Bu hesabın yönetim yetkisi yok.";
        girisUyari.hidden = false;
      }
      girisEkrani.hidden = false;
      panelEkrani.hidden = true;
    }
  });

  /* --- Sekmeler --- */
  tumu(".sekme").forEach((sekme) => {
    sekme.addEventListener("click", () => {
      tumu(".sekme").forEach((s) => s.classList.remove("sekme--aktif"));
      sekme.classList.add("sekme--aktif");
      const hedef = sekme.dataset.sekme;
      sec("#notlarBolum").hidden = hedef !== "notlar";
      sec("#sohbetlerBolum").hidden = hedef !== "sohbetler";
    });
  });

  /* --- Notlar --- */
  function notlariDinle() {
    const sorgu = query(collection(vt, "notlar"), orderBy("tarih", "desc"));
    onSnapshot(sorgu, (anlik) => {
      const liste = sec("#notListe");
      liste.innerHTML = "";
      sec("#notBos").hidden = !anlik.empty;
      let okunmamis = 0;

      anlik.forEach((belge) => {
        const veri = belge.data();
        if (!veri.okundu) okunmamis += 1;

        const oge = document.createElement("li");
        oge.className = "kart kart--tiklanir" + (veri.okundu ? "" : " kart--yeni");
        oge.innerHTML =
          '<div class="kart__ust"><span class="kart__ad"></span><span class="kart__tarih"></span></div>' +
          '<p class="kart__metin"></p>';
        oge.querySelector(".kart__ad").textContent = veri.ad || "isimsiz";
        oge.querySelector(".kart__tarih").textContent = tarihYaz(veri.tarih);
        oge.querySelector(".kart__metin").textContent = veri.mesaj || "";

        oge.addEventListener("click", () => {
          if (!veri.okundu) updateDoc(doc(vt, "notlar", belge.id), { okundu: true });
        });

        liste.appendChild(oge);
      });

      sec("#notSayisi").textContent = String(okunmamis);
      notOkunmamis = okunmamis;
      basligiGuncelle();
    });
  }

  /* --- Sohbetler --- */
  function sohbetleriDinle() {
    const sorgu = query(collection(vt, "sohbetler"), orderBy("sonTarih", "desc"));
    onSnapshot(sorgu, (anlik) => {
      const liste = sec("#sohbetListe");
      liste.innerHTML = "";
      sec("#sohbetBos").hidden = !anlik.empty;

      let okunmamisSohbet = 0;

      anlik.forEach((belge) => {
        const veri = belge.data();
        const yeni = veri.sonYazan === "zara" && veri.yapimciOkudu === false;
        if (yeni) okunmamisSohbet += 1;

        const oge = document.createElement("li");
        oge.className = "kart kart--tiklanir"
          + (belge.id === acikSohbetId ? " kart--secili" : "")
          + (yeni ? " kart--yeni" : "");
        oge.innerHTML =
          '<div class="kart__ust"><span class="kart__ad"></span><span class="kart__tarih"></span></div>' +
          '<p class="kart__metin"></p>';
        oge.querySelector(".kart__ad").textContent = veri.baslik || "Zara";
        oge.querySelector(".kart__tarih").textContent = tarihYaz(veri.sonTarih);
        oge.querySelector(".kart__metin").textContent = veri.sonMesaj || "";
        oge.addEventListener("click", () => sohbetiAc(belge.id, veri.baslik || "Zara"));
        liste.appendChild(oge);
      });

      sec("#sohbetSayisi").textContent = String(okunmamisSohbet || anlik.size);
      sohbetOkunmamis = okunmamisSohbet;
      basligiGuncelle();

      if (okunmamisSohbet > oncekiOkunmamis && oncekiOkunmamis >= 0) bildirimGoster();
      oncekiOkunmamis = okunmamisSohbet;
    });
  }

  function sohbetiAc(id, baslik) {
    acikSohbetId = id;
    setDoc(doc(vt, "sohbetler", id), { yapimciOkudu: true }, { merge: true });
    sec("#sohbetPencere").hidden = false;
    sec("#sohbetBaslik").textContent = baslik;

    const odaSil = sec("#odaSil");
    if (odaSil) {
      odaSil.onclick = function () {
        if (!window.confirm("Bu sohbet odası listeden silinsin mi?")) { return; }
        deleteDoc(doc(vt, "sohbetler", id));
        sec("#sohbetPencere").hidden = true;
        acikSohbetId = null;
      };
    }

    if (mesajDinleyici) mesajDinleyici();

    const sorgu = query(collection(vt, "sohbetler", id, "mesajlar"), orderBy("tarih", "asc"));
    mesajDinleyici = onSnapshot(sorgu, (anlik) => {
      const kutu = sec("#mesajlar");
      kutu.innerHTML = "";
      anlik.forEach((belge) => {
        const veri = belge.data();
        const balon = document.createElement("div");
        balon.className = "balon " + (veri.kim === "yapimci" ? "balon--yapimci" : "balon--zara");

        const yazi = document.createElement("span");
        yazi.textContent = veri.metin;
        balon.appendChild(yazi);

        const sil = document.createElement("button");
        sil.type = "button";
        sil.className = "balon__sil";
        sil.title = "Bu mesajı sil";
        sil.setAttribute("aria-label", "Bu mesajı sil");
        sil.textContent = "×";
        sil.addEventListener("click", function () {
          if (!window.confirm("Bu mesaj silinsin mi?")) { return; }
          deleteDoc(doc(vt, "sohbetler", id, "mesajlar", belge.id));
        });
        balon.appendChild(sil);

        kutu.appendChild(balon);
      });
      kutu.scrollTop = kutu.scrollHeight;
    });
  }

  sec("#cevapForm").addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const girdi = sec("#cevapGirdi");
    const metin = girdi.value.trim();
    if (!metin || !acikSohbetId) return;
    girdi.value = "";

    await addDoc(collection(vt, "sohbetler", acikSohbetId, "mesajlar"), {
      kim: "yapimci",
      metin: metin,
      tarih: serverTimestamp()
    });
    await setDoc(doc(vt, "sohbetler", acikSohbetId), {
      sonMesaj: "Sen: " + metin.slice(0, 70),
      sonTarih: serverTimestamp(),
      sonYazan: "yapimci",
      yapimciOkudu: true
    }, { merge: true });
  });
}
