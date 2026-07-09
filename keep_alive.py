from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "BIST Bot 7/24 Aktif ve Calisiyor!"

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
