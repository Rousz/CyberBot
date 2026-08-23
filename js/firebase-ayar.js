/* ============================================================
   FIREBASE AYARLARI
   ------------------------------------------------------------
   BURAYI DOLDUR. Değerleri Firebase konsolundan alacaksın:
   Proje Ayarları (dişli) → Genel → "Uygulamalarınız" → Web app → SDK yapılandırması

   Bu değerlerin herkese açık olması normaldir; güvenlik, Firestore
   kurallarıyla sağlanıyor (bkz. FIREBASE-KURULUM.md).
   ============================================================ */

export const FIREBASE_AYAR = {
  apiKey: "",
  authDomain: "",
  projectId: "",
  storageBucket: "",
  messagingSenderId: "",
  appId: ""
};

// BURAYA KENDİ E-POSTANI YAZ — yönetim sayfasına sadece bu hesap girebilir
export const YONETICI_EPOSTA = "";

// Ayarlar doldurulmuş mu?
export const AYAR_HAZIR = Boolean(FIREBASE_AYAR.apiKey && FIREBASE_AYAR.projectId);
