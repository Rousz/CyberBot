# Not & Sohbet Sistemi — Kurulum

Sitedeki "Yapımcıya Not İlet" bölümü ve gizli yönetim sayfası Firebase üzerinde çalışır.
Aşağıdaki adımlar bir kez yapılır, hepsi ücretsiz. Telefondan da yapılabilir.

---

## 1. Firebase projesi aç

1. **console.firebase.google.com** adresine Google hesabınla gir
2. **Proje ekle** → bir isim ver (örn. `zara-site`) → Google Analytics'i **kapat** → oluştur

## 2. Firestore veritabanını aç

1. Sol menü → **Build → Firestore Database** → **Veritabanı oluştur**
2. **Production mode** seç
3. Konum: `eur3` ya da `europe-west` (Türkiye'ye en yakını)

## 3. Girişleri aç

1. Sol menü → **Build → Authentication** → **Başla**
2. **Sign-in method** sekmesi:
   - **Anonim** → etkinleştir  (ziyaretçilerin not/mesaj yazabilmesi için)
   - **E-posta/Şifre** → etkinleştir  (senin yönetim girişin için)
3. **Users** sekmesi → **Kullanıcı ekle** → kendi e-postan + bir şifre belirle
   → Yönetim sayfasına bu bilgilerle gireceksin

## 4. Güvenlik kurallarını yapıştır

**Firestore Database → Rules** sekmesine gir, içindekini sil, aşağıdakini yapıştır.
`SENIN@EPOSTAN.com` yazan yeri kendi e-postanla değiştir, sonra **Yayınla**.

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function yonetici() {
      return request.auth != null
             && request.auth.token.email == 'SENIN@EPOSTAN.com';
    }

    // Notlar: herkes yazabilir, sadece yönetici okuyabilir
    match /notlar/{notId} {
      allow create: if request.auth != null
                    && request.resource.data.mesaj is string
                    && request.resource.data.mesaj.size() > 0
                    && request.resource.data.mesaj.size() < 1000;
      allow read, update, delete: if yonetici();
    }

    // Sohbetler: herkes kendi odasını görür, yönetici hepsini görür
    match /sohbetler/{sohbetId} {
      allow create: if request.auth != null
                    && request.resource.data.sahip == request.auth.uid;
      allow read, update: if yonetici()
                          || (request.auth != null && resource.data.sahip == request.auth.uid);
      allow delete: if yonetici();

      match /mesajlar/{mesajId} {
        function sahibi() {
          return request.auth != null
                 && get(/databases/$(database)/documents/sohbetler/$(sohbetId)).data.sahip == request.auth.uid;
        }
        allow read: if yonetici() || sahibi();
        allow create: if (yonetici() || sahibi())
                      && request.resource.data.metin is string
                      && request.resource.data.metin.size() < 1000;
        allow update, delete: if false;
      }
    }
  }
}
```

Bu kurallar sunucu tarafında çalışır. Yani kodu okuyan biri bile başkasının
notlarını ya da sohbetini göremez — okuma izni sadece senin e-postana bağlı.

## 5. Ayarları siteye gir

1. **Proje Ayarları** (sol üstteki dişli) → **Genel** → sayfanın altı → **Uygulamalarınız**
2. Web simgesine (`</>`) bas → bir takma ad ver → **Uygulamayı kaydet**
3. Ekranda çıkan `firebaseConfig` değerlerini `js/firebase-ayar.js` dosyasına yaz:

```js
export const FIREBASE_AYAR = {
  apiKey: "...",
  authDomain: "...",
  projectId: "...",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};

export const YONETICI_EPOSTA = "senin@epostan.com";
```

Bu değerlerin herkese açık olması normaldir; Firebase böyle çalışır.
Güvenliği 4. adımdaki kurallar sağlar.

---

## Kullanım

- **Site:** `zaraisimlihanimefendi.com` → en altta "Yapımcıya Not İlet" bölümü
- **Yönetim:** `zaraisimlihanimefendi.com/yonetim.html` → e-posta + şifrenle giriş

Yönetim sayfasında iki sekme var: **Notlar** (okunmamışlar pembe çizgili) ve
**Sohbetler** (bir sohbete tıkla, alttaki kutudan cevap yaz).

## Güvenlik sorusu

Soru `index.html` içinde, cevap `js/not.js` en üstünde:

```js
const DOGRU_CEVAP_BASLANGIC = "et";
```

"Et", "et", "eti", "et yemekleri" gibi cevapların hepsi kabul edilir;
büyük/küçük harf ve Türkçe karakter farkı önemsenmez.

Doğru cevap verilince çıkan büyük mesaj da aynı dosyada (`BUYUK_MESAJ`).

## Ayarlar girilmeden önce

`js/firebase-ayar.js` boşken site sorunsuz çalışır; not bölümü sadece
"Bu bölüm birazdan açılıyor." yazar. Kimseye bozuk bir form görünmez.
