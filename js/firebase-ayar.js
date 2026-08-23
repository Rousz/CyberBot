/* ============================================================
   FIREBASE AYARLARI
   ------------------------------------------------------------
   Bu değerler Firebase konsolundan gelir ve herkese açık olması
   normaldir (Firebase böyle çalışır). Güvenliği Firestore
   kuralları sağlar — bkz. FIREBASE-KURULUM.md
   ============================================================ */

export const FIREBASE_AYAR = {
  apiKey: "AIzaSyDerQuEyBYL2bFw0LW2WtJWzvaSa-vEyik",
  authDomain: "zaraisimlihanimefendi-16e8b.firebaseapp.com",
  projectId: "zaraisimlihanimefendi-16e8b",
  storageBucket: "zaraisimlihanimefendi-16e8b.firebasestorage.app",
  messagingSenderId: "253896289924",
  appId: "1:253896289924:web:c5edfc568848147f6b9cd1"
};

/* Yönetim sayfasına yalnızca bu e-posta girebilir.
   Firestore kurallarındaki e-postayla aynı olmak zorunda. */
export const YONETICI_EPOSTA = "berkantaha20051@gmail.com";

// Ayarlar doldurulmuş mu?
export const AYAR_HAZIR = Boolean(FIREBASE_AYAR.apiKey && FIREBASE_AYAR.projectId);
