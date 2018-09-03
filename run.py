from dispatchsrht.app import app
from srht.config import cfg, cfgi

import os

app.static_folder = os.path.join(os.getcwd(), "static")

if __name__ == '__main__':
    app.run(host=cfg("dispatch.sr.ht", "debug-host"),
            port=cfgi("dispatch.sr.ht", "debug-port"),
            debug=True)
