"""Clinical Signal: inpatient admission hotspot detection.

The package has three parts:

    data_loader   reads the admissions file into daily counts
    detection     finds, groups, and ranks hotspots
    routes        serves the page and the JSON it needs
    causes        part two: lines outside items up against a hotspot
    reviews       a person's decision on each possible cause
    actions       part three: the owner and recommendation for each confirmed cause
"""

from __future__ import annotations

from flask import Flask

from pathlib import Path

import config
from . import actions, causes
from .data_loader import load
from .detection import Engine
from .reviews import REVIEWS_FILE, Reviews


def create_app(data_dir=None, as_of=None, reviews_path=None, decisions_path=None) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    dataset = load(data_dir or config.DATA_DIR, as_of)
    engine = Engine(dataset)
    engine.run("all")  # run once at startup so the first page load is instant
    app.extensions["engine"] = engine
    app.extensions["summaries"] = {}
    # Part two. The outside items live in their own folder (external_data) and are loaded after
    # detection has run: nothing in them can change what is detected.
    app.extensions["outside"] = causes.load_items(data_dir or config.EXTERNAL_DIR)
    app.extensions["causes"] = {}
    app.extensions["reviews"] = Reviews(reviews_path or Path(data_dir or config.DATA_DIR) / REVIEWS_FILE)

    # Part three. The mapping from a kind of cause to an owner and a recommendation, and what people decided.
    app.extensions["mapping"] = actions.load_mapping(data_dir or config.DATA_DIR)
    app.extensions["tailored"] = {}
    app.extensions["decisions"] = actions.Decisions(decisions_path or Path(data_dir or config.DATA_DIR) / actions.DECISIONS_FILE)

    from .routes import bp
    app.register_blueprint(bp)
    return app
