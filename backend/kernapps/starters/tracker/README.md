# Tracker

Log a number for something (a chicken, a plant, a car) and watch it change over time.

* `app.py`: the server (Python standard library only). Data lives in `$APP_DATA_DIR/tracker.db`.
* `static/`: the page, its styles and script.

Kern serves the app at `/<path>/`, so the page uses relative URLs (`api/entries`, not `/api/entries`).
