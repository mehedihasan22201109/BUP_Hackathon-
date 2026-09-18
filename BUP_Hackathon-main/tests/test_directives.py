"""Deterministic directive validation tests."""

from __future__ import annotations

from app.schemas import DirectiveType
from app.validation.directives import normalize_entry, normalize_entries


def test_normalize_no_op_when_llm_returns_prose_only():
    out = normalize_entry(0, None)
    assert out["note_index"] == 0
    assert out["applies"] is False
    assert out["directive_type"] == DirectiveType.NO_OP.value
    assert out["structured_adjustment"] is None
    assert out["explanation"]


def test_normalize_unknown_directive_becomes_no_op():
    out = normalize_entry(0, {"note_index": 0, "directive_type": "frobnicate"})
    assert out["directive_type"] == "no_op"
    assert out["applies"] is False


def test_normalize_solar_reduction_clamps_factor():
    out = normalize_entry(
        0,
        {
            "note_index": 0,
            "directive_type": "solar_reduction",
            "applies": True,
            "structured_adjustment": {"factor": 1.7, "hours": [10, 11]},
            "explanation": "x",
        },
    )
    assert out["directive_type"] == "solar_reduction"
    assert out["applies"] is True
    assert out["structured_adjustment"]["factor"] == 1.0  # clamped
    assert out["structured_adjustment"]["hours"] == [10, 11]


def test_normalize_solar_reduction_strips_invalid_hours():
    out = normalize_entry(
        0,
        {
            "note_index": 0,
            "directive_type": "solar_reduction",
            "applies": True,
            "structured_adjustment": {"factor": 0.5, "hours": [9, 9, 24, -1, "x"]},
        },
    )
    assert out["structured_adjustment"]["hours"] == [9]


def test_normalize_reserve_clamps_to_battery_envelope(sample_battery):
    out = normalize_entry(
        0,
        {
            "note_index": 0,
            "directive_type": "minimum_battery_reserve",
            "applies": True,
            "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 9999.0},
        },
        battery=sample_battery,
    )
    sa = out["structured_adjustment"]
    # Clamped to capacity
    assert sa["minimum_energy_kwh"] == sample_battery.capacity_kwh


def test_normalize_max_grid_rejects_negative():
    out = normalize_entry(
        0,
        {
            "note_index": 0,
            "directive_type": "max_grid_window",
            "applies": True,
            "structured_adjustment": {"hours": [19, 20], "max_grid_kwh": -5.0},
        },
    )
    assert out["structured_adjustment"]["max_grid_kwh"] == 0.0


def test_normalize_entries_aligns_to_note_order(sample_battery):
    raw = [
        {"note_index": 0, "directive_type": "no_charge_window", "applies": True,
         "structured_adjustment": {"hours": [2, 3, 4]}},
        {"note_index": 3, "directive_type": "no_op", "applies": False,
         "structured_adjustment": None},
    ]
    notes = ["first", "second", "third", "fourth"]
    out = normalize_entries(raw, notes, battery=sample_battery)
    assert [e["note_index"] for e in out] == [0, 1, 2, 3]
    # The LLM "lost" note 1, 2, and gave a bad note_index for note 3; the
    # validator must still emit one entry per input note.
    assert out[0]["directive_type"] == "no_charge_window"
    assert out[1]["directive_type"] == "no_op"
    assert out[2]["directive_type"] == "no_op"
    assert out[3]["directive_type"] == "no_op"


def test_normalize_entries_handles_total_garbage(sample_battery):
    out = normalize_entries("not a list", ["n1", "n2"], battery=sample_battery)
    assert all(e["directive_type"] == "no_op" for e in out)
    assert [e["note_index"] for e in out] == [0, 1]
