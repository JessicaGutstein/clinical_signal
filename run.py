"""Starts the Clinical Signal prototype.

    python run.py

The page opens in your browser at http://127.0.0.1:5050. Press Ctrl+C in this
window to stop. Add --no-browser to start the server without opening a page.
"""

import sys
import threading
import webbrowser

import config
from clinical_signal import create_app

if __name__ == "__main__":
    print("Loading admissions and running detection...")
    app = create_app()
    engine = app.extensions["engine"]
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"Data as of {engine.ds.as_of}. {len(engine.run('all').alerts)} signals found.")
    print(f"Open {url} in your browser. Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=config.HOST, port=config.PORT, debug=False)
