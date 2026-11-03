PILOT_2_FEATURES = ["adaptive cruise", "lane keeping"]
PILOT_3_FEATURES = PILOT_2_FEATURES + [
    "traffic jam assist",
    "automatic lane change (with Pilot Plus)",
]


def pilot_features(version: int) -> list[str]:
    """Voltrieve Pilot features for a version: 3 builds on 2."""
    return PILOT_3_FEATURES if version >= 3 else PILOT_2_FEATURES
