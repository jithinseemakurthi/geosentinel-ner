"""Tests for the canonical NER district registry."""
from geosentinel_shared.districts import (
    DISTRICT_COORDS,
    NORTHEAST_ABBREVIATIONS,
    NORTHEAST_STATE_LOCATIONS,
    NORTHEAST_STATES,
)


def test_all_eight_ner_states_present():
    assert len(NORTHEAST_STATES) == 8
    assert set(NORTHEAST_STATES) == set(NORTHEAST_STATE_LOCATIONS)


def test_every_representative_district_has_coordinates():
    for state, district in NORTHEAST_STATE_LOCATIONS.items():
        assert district in DISTRICT_COORDS, f"{state}: missing coords for {district}"


def test_coordinates_are_valid_wgs84():
    for district, coords in DISTRICT_COORDS.items():
        lat, lon = coords["lat"], coords["lon"]
        assert 20 < lat < 30, f"{district}: lat {lat} outside NER"
        assert 85 < lon < 98, f"{district}: lon {lon} outside NER"


def test_abbreviations_cover_all_states():
    assert set(NORTHEAST_ABBREVIATIONS) == set(NORTHEAST_STATES)
    assert all(len(code) == 2 for code in NORTHEAST_ABBREVIATIONS.values())
