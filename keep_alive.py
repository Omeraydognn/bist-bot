from flask import Flask
from threading import Thread
import os
import subprocess
from datetime import datetime

app = Flask(__name__)

# Hangi surumun calistigini tarayicidan gorebilmek icin surum bilgisi.
# Deploy dogrulamasi: Render URL'ini acinca commit hash'i gorunur.
BOT_VERSION = "v3.1 - tatil takvimi + AI Kural 0 + backtest ayarlari + kar realizasyonu"
try:
    GIT_COMMIT = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stderr=subprocess.DEVNULL, text=True,
    ).strip()
except Exception:
    GIT_COMMIT = "bilinmiyor"

STARTED_AT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route('/')
def home():
    return (
        f"BIST Bot 7/24 Aktif ve Calisiyor!<br>"
        f"Surum: {BOT_VERSION}<br>"
        f"Commit: {GIT_COMMIT}<br>"
        f"Baslatilma: {STARTED_AT}"
    )


def run():
    # Render'in atadigi portu alir, yoksa 8080 kullanir
    port = int(os.environ.get('PORT', 8080))
    # Werkzeug loglarini kapatarak terminali kirletmesini onle
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    app.run(host='0.0.0.0', port=port)


def keep_alive():
    """Arka planda kucuk bir web sunucusu baslatarak Render'i kandirir."""
    t = Thread(target=run)
    t.daemon = True
    t.start()
