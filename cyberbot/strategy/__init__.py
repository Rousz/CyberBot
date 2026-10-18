"""CyberScalp stratejisinin saf (Freqtrade'siz) mantığı.

- defaults.py : STRATEGY_DEFAULTS (config "cyberbot.strategy" bölümü)
- core.py     : göstergeler, rejim, tetik, stop/hedef, puan (pandas + talib)
- ranking.py  : aynı mumda birden çok sinyal -> en yüksek puan önce; Binance önceliği
- health.py   : borsa sağlık durum makinesi (WEEX verisi bayatladı -> yeni işlem yok)

Freqtrade'e bağlı ince katman: user_data/strategies/CyberScalp.py
"""
