# Test fixture'ları

Birim testleri internetsiz çalışır. Bu klasördeki JSON dosyaları borsa
cevaplarının örnekleridir.

- Şu anki dosyalar ccxt 4.5.88 kaynak kodundaki örnek cevaplardan ve Binance'in
  bilinen cevap biçimlerinden **elle türetildi**.
- PC'de `01_connection_test.bat` çalışınca gerçek (küçültülmüş, herkese açık)
  cevaplar `reports/samples/` klasörüne yazılır. Bunlar repoya gelince fixture'lar
  gerçek örneklerle değiştirilecek.
- Gizli bilgi (token, anahtar, bakiye, chat id) içeren cevaplar asla buraya girmez.
