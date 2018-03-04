from dispatchsrht.app import app
from srht.config import cfg, cfgi

import os

app.static_folder = os.path.join(os.getcwd(), "static")

if __name__ == '__main__':
    app.run(host=cfg("debug", "debug-host"),
            port=cfgi("debug", "debug-port"),
            debug=True)
