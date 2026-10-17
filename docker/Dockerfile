# CyberBot imaji: Freqtrade 2026.9 + ccxt 4.5.88 + WEEX borsa sinifi.
# Build baglamina sadece freqtrade_ext/weex.py girer (.dockerignore); .env asla girmez.
FROM freqtradeorg/freqtrade:2026.9

USER root
# /data: veritabanlari icin Docker volume baglanma noktasi (ftuser yazabilsin)
RUN mkdir -p /data && chown ftuser:ftuser /data
USER ftuser

# ccxt 4.5.84 (imajdaki) WEEX'in {"code":"200","msg":"success"} cevaplarini hata sayiyor ve
# bozuk bir piyasa kaydinda load_markets'i dusuruyor; 4.5.88 ikisini de duzeltir.
RUN pip install --user --no-cache-dir "ccxt==4.5.88"

COPY --chown=ftuser:ftuser freqtrade_ext/weex.py /freqtrade/freqtrade/exchange/weex.py
RUN printf '\n# CyberBot: WEEX USDT-M futures\nfrom freqtrade.exchange.weex import Weex  # noqa: E402\n' \
        >> /freqtrade/freqtrade/exchange/__init__.py \
    && python -c "import ccxt, freqtrade.exchange as fx; assert fx.Weex.__name__ == 'Weex'; assert ccxt.__version__ == '4.5.88'; print('CyberBot imaji hazir, ccxt', ccxt.__version__)"

ENV PYTHONPATH=/repo \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=UTC \
    CYBERBOT_REPO_DIR=/repo \
    CYBERBOT_DATA_DIR=/data
