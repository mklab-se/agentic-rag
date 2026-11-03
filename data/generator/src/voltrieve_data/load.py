from pathlib import Path

import yaml

from voltrieve_data.model import Catalog


def load_catalog(path: Path) -> Catalog:
    with open(path, encoding="utf-8") as f:
        return Catalog.model_validate(yaml.safe_load(f))
