"""parse_tle: fixed-column parsing, checksum, epoch, and derived geometry.

The reference element set is the widely-published SGP4 verification TLE for
the ISS (NORAD 25544, epoch 2008-264), from Vallado et al., "Revisiting
Spacetrack Report #3" (AIAA 2006-6753) and reproduced in the sgp4 library's
own test data. Its two modulo-10 check digits are both 7; that is verified
here by hand against the documented checksum rule, so these tests compare
against an external reference, never against our own output.

The 1998-epoch line 1 below is the same reference line with only its epoch
year digit changed 0 -> 9 (a +9 shift in the digit sum, so the check digit
moves 7 -> 6). It is a deliberate splice used solely to exercise the
19xx/20xx two-digit-year pivot end to end; its orbital elements are not
claimed to be physically meaningful for 1998.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from prahari_orbital.ingest import (
    EARTH_RADIUS_KM,
    CatalogFetchError,
    InvalidTLE,
    TLERecord,
    _expected_check_digit,
    _percentile,
    _verify_checksum,
    build_catalog_objects,
    classify_object_type,
    fetch_catalog,
    parse_tle,
    parse_tle_block,
    snapshots,
    validate_tle_pair,
)
from prahari_orbital.models import ObjectType

ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
ISS_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"

# Same as ISS_LINE1 with epoch year 08 -> 98 and check digit 7 -> 6 (see module docstring).
ISS_LINE1_1998 = "1 25544U 98067A   98264.51782528 -.00002182  00000-0 -11606-4 0  2926"


def test_reference_lines_are_69_chars() -> None:
    # Guards the test fixtures themselves, not production code.
    assert len(ISS_LINE1) == 69
    assert len(ISS_LINE2) == 69
    assert len(ISS_LINE1_1998) == 69


def test_valid_iss_tle_parses_to_expected_elements() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)

    assert isinstance(rec, TLERecord)
    assert rec.norad_id == 25544
    assert rec.classification == "U"
    assert rec.intl_designator == "98067A"
    # Published inclination for this element set is 51.6416 deg.
    assert rec.inclination_deg == pytest.approx(51.64, abs=1e-2)
    assert rec.raan_deg == pytest.approx(247.4627, abs=1e-3)
    assert rec.arg_perigee_deg == pytest.approx(130.5360, abs=1e-3)
    assert rec.mean_anomaly_deg == pytest.approx(325.0288, abs=1e-3)
    assert rec.mean_motion_rev_per_day == pytest.approx(15.72125391, abs=1e-6)


def test_name_keeps_interior_spaces_and_strips_3le_prefix() -> None:
    # Fixed-column parsing must not tokenise on whitespace.
    rec = parse_tle("0 " + ISS_NAME + "  ", ISS_LINE1, ISS_LINE2)
    assert rec.name == "ISS (ZARYA)"


def test_eccentricity_implied_decimal_point() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)
    # Field is "0006703" with an implied leading "0." -> 0.0006703, not 6703.
    assert rec.eccentricity == pytest.approx(0.0006703, abs=1e-10)
    assert 0.0 <= rec.eccentricity < 1.0


def test_bstar_implied_decimal_exponential() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)
    # Field "-11606-4" -> -0.11606e-4.
    assert rec.bstar == pytest.approx(-1.1606e-5, rel=1e-9)


def test_epoch_is_timezone_aware_utc_20xx() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)

    assert rec.epoch.tzinfo is not None
    assert rec.epoch.utcoffset() == timedelta(0)
    # Year 08 -> 2008; day-of-year 264.51782528 is 2008-09-20 ~12:25 UTC.
    assert rec.epoch.year == 2008
    assert (rec.epoch.month, rec.epoch.day) == (9, 20)
    assert rec.epoch.hour == 12


def test_epoch_two_digit_year_pivot_19xx() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1_1998, ISS_LINE2)
    # Year 98 is >= 57, so it resolves to 1998, not 2098.
    assert rec.epoch.year == 1998
    assert rec.epoch.tzinfo is not None
    assert rec.epoch.utcoffset() == timedelta(0)


def test_epoch_age_hours_is_nonnegative_and_large_for_2008_epoch() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)
    # Epoch is 2008; parse time is "now" -> well over a decade of hours.
    assert rec.epoch_age_hours > 10 * 365 * 24


def test_derived_altitudes_put_iss_in_low_earth_orbit() -> None:
    rec = parse_tle(ISS_NAME, ISS_LINE1, ISS_LINE2)

    # Independent physical fact: in Sept 2008 the ISS orbited at ~340-360 km,
    # near-circular. Loose bounds so the assertion tests the derivation, not
    # a fragile exact value.
    assert 300.0 < rec.perigee_km < 420.0
    assert 300.0 < rec.apogee_km < 430.0
    assert rec.apogee_km >= rec.perigee_km
    assert rec.apogee_km - rec.perigee_km < 30.0
    # a(1-e) and a(1+e) straddle the semi-major axis by construction.
    assert rec.perigee_km + EARTH_RADIUS_KM < rec.semi_major_axis_km < rec.apogee_km + EARTH_RADIUS_KM


def test_corrupted_checksum_raises_invalid_tle() -> None:
    corrupted = ISS_LINE1[:-1] + "8"  # real check digit is 7
    with pytest.raises(InvalidTLE, match="checksum"):
        parse_tle(ISS_NAME, corrupted, ISS_LINE2)


def test_wrong_line_length_raises_invalid_tle() -> None:
    with pytest.raises(InvalidTLE, match="69 characters"):
        parse_tle(ISS_NAME, ISS_LINE1[:-1], ISS_LINE2)


def test_norad_id_mismatch_between_lines_raises_invalid_tle() -> None:
    # Change line 2's satellite number field only; fix up its check digit so
    # the failure under test is the id mismatch, not the checksum.
    mangled_body = "2 25545" + ISS_LINE2[7:68]
    mangled = mangled_body + str(_expected_check_digit(mangled_body))
    with pytest.raises(InvalidTLE, match="NORAD id mismatch"):
        parse_tle(ISS_NAME, ISS_LINE1, mangled)


# --------------------------------------------------------------------------- #
# Checksum validation: the positive half of the property.                     #
#                                                                             #
# test_corrupted_checksum_raises_invalid_tle above proves corruption is       #
# rejected. This proves a known-good real element set is *accepted* — the     #
# published ISS reference lines, whose two mod-10 check digits are both 7     #
# (verified by hand in the module docstring, an external reference).          #
# --------------------------------------------------------------------------- #


def test_known_good_real_tle_passes_checksum_validation() -> None:
    # _verify_checksum returns None (does not raise) when the check digit is right.
    assert _verify_checksum(ISS_LINE1, which="line 1") is None
    assert _verify_checksum(ISS_LINE2, which="line 2") is None
    # The digits themselves match the externally-published value.
    assert _expected_check_digit(ISS_LINE1) == 7
    assert _expected_check_digit(ISS_LINE2) == 7
    assert ISS_LINE1[68] == "7"
    assert ISS_LINE2[68] == "7"
    # And the same lines pass the drop-not-raise pair validator.
    assert validate_tle_pair(ISS_LINE1, ISS_LINE2) is True


def test_validate_tle_pair_drops_corruption_without_raising() -> None:
    corrupted = ISS_LINE1[:-1] + "8"  # real check digit is 7
    assert validate_tle_pair(corrupted, ISS_LINE2) is False
    assert validate_tle_pair(ISS_LINE1[:-1], ISS_LINE2) is False  # wrong length
    assert validate_tle_pair(ISS_LINE2, ISS_LINE1) is False  # swapped line numbers


# --------------------------------------------------------------------------- #
# parse_tle_block / classify_object_type                                      #
# --------------------------------------------------------------------------- #

RAW_ONE = "\r\n".join([ISS_NAME, ISS_LINE1, ISS_LINE2]) + "\r\n"
RAW_TWO = "\r\n".join([ISS_NAME, ISS_LINE1, ISS_LINE2, ISS_NAME, ISS_LINE1, ISS_LINE2]) + "\r\n"


def test_parse_tle_block_splits_three_line_records() -> None:
    records = parse_tle_block(RAW_TWO)
    assert len(records) == 2
    assert records[0] == ("ISS (ZARYA)", ISS_LINE1, ISS_LINE2)


def test_parse_tle_block_tolerates_trailing_blank_lines() -> None:
    assert len(parse_tle_block(RAW_ONE + "\r\n\r\n")) == 1


def test_parse_tle_block_rejects_non_multiple_of_three() -> None:
    with pytest.raises(ValueError, match="multiple of 3"):
        parse_tle_block("\r\n".join([ISS_NAME, ISS_LINE1]) + "\r\n")


def test_parse_tle_block_rejects_wrong_line_prefix() -> None:
    with pytest.raises(ValueError, match="line 1 must start"):
        parse_tle_block("\r\n".join([ISS_NAME, ISS_LINE2, ISS_LINE1]) + "\r\n")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("COSMOS 1408 DEB", ObjectType.DEBRIS),
        ("FALCON 9 DEB", ObjectType.DEBRIS),
        ("SL-16 R/B", ObjectType.ROCKET_BODY),
        ("ATLAS 5 CENTAUR R/B", ObjectType.ROCKET_BODY),
        ("ISS (ZARYA)", ObjectType.PAYLOAD),
        ("STARLINK-1234", ObjectType.PAYLOAD),
        ("", ObjectType.UNKNOWN),
    ],
)
def test_classify_object_type(name: str, expected: ObjectType) -> None:
    assert classify_object_type(name) == expected


# --------------------------------------------------------------------------- #
# build_catalog_objects                                                       #
# --------------------------------------------------------------------------- #


def test_build_catalog_objects_from_iss_triple() -> None:
    now = "2008-09-21T00:00:00+00:00"  # ~12 h after the ISS epoch
    objs = build_catalog_objects([(ISS_NAME, ISS_LINE1, ISS_LINE2)], now_utc=now)

    assert len(objs) == 1
    obj = objs[0]
    assert obj.norad_id == 25544
    assert obj.object_type == ObjectType.PAYLOAD
    assert obj.rcs_size.value == "UNKNOWN"
    assert obj.radius_m > 0
    # epoch_age_hours is measured from the caller's now_utc, not wall-clock.
    assert obj.epoch_age_hours == pytest.approx(11.55, abs=0.5)
    assert 300.0 < obj.perigee_km < 420.0


def test_build_catalog_objects_accepts_bare_z_suffix() -> None:
    objs = build_catalog_objects([(ISS_NAME, ISS_LINE1, ISS_LINE2)], now_utc="2008-09-21T00:00:00Z")
    assert objs[0].epoch_age_hours > 0


# --------------------------------------------------------------------------- #
# _percentile                                                                 #
# --------------------------------------------------------------------------- #


def test_percentile_linear_interpolation() -> None:
    values = [0.0, 10.0, 20.0, 30.0, 40.0]  # already sorted
    assert _percentile(values, 0.0) == 0.0
    assert _percentile(values, 50.0) == 20.0
    assert _percentile(values, 100.0) == 40.0
    assert _percentile(values, 90.0) == pytest.approx(36.0)
    assert _percentile([], 50.0) == 0.0


# --------------------------------------------------------------------------- #
# fetch_catalog + snapshots: caching, offline, checksum-skip                  #
# --------------------------------------------------------------------------- #


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def test_snapshots_empty_when_cache_dir_absent(tmp_path) -> None:
    assert snapshots(tmp_path / "nope") == []


def test_snapshots_sorted_oldest_first(tmp_path) -> None:
    older = tmp_path / "active_20200101T000000Z.tle"
    newer = tmp_path / "active_20240101T000000Z.tle"
    other = tmp_path / "stations_20220101T000000Z.tle"
    for p in (newer, other, older):
        p.write_text(RAW_ONE, encoding="utf-8")
    (tmp_path / "not-a-snapshot.tle").write_text("junk", encoding="utf-8")

    result = snapshots(tmp_path)
    assert [p.name for _, p in result] == [older.name, other.name, newer.name]
    assert all(ts.tzinfo is not None for ts, _ in result)


def test_fetch_catalog_offline_without_cache_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="no cached snapshot"):
        fetch_catalog(group="active", cache_dir=tmp_path, offline=True)


def test_fetch_catalog_offline_reads_newest_cache(tmp_path, monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("offline=True must not touch the network")

    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", _boom)
    (tmp_path / "active_20200101T000000Z.tle").write_text(RAW_ONE, encoding="utf-8")
    (tmp_path / "active_20240101T000000Z.tle").write_text(RAW_TWO, encoding="utf-8")

    snap = fetch_catalog(group="active", cache_dir=tmp_path, offline=True)
    assert snap.from_cache is True
    assert snap.parsed_count == 2  # the newer file has two records
    assert snap.source_path.name == "active_20240101T000000Z.tle"
    assert snap.fetched_at == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_fetch_catalog_writes_cache_then_reuses_within_six_hours(tmp_path, monkeypatch) -> None:
    calls = {"n": 0}

    def _fake_fetch(url: str, **_kwargs) -> str:
        calls["n"] += 1
        assert "GROUP=active" in url and "FORMAT=tle" in url
        return RAW_TWO

    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", _fake_fetch)

    first = fetch_catalog(group="active", cache_dir=tmp_path)
    assert first.from_cache is False
    assert first.parsed_count == 2
    assert calls["n"] == 1
    assert first.source_path.exists()

    second = fetch_catalog(group="active", cache_dir=tmp_path)
    assert second.from_cache is True
    assert calls["n"] == 1  # no second network hit
    assert second.source_path == first.source_path


def test_fetch_catalog_refetches_when_cache_is_stale(tmp_path, monkeypatch) -> None:
    stale = tmp_path / f"active_{_stamp(datetime(2020, 1, 1, tzinfo=timezone.utc))}.tle"
    stale.write_text(RAW_ONE, encoding="utf-8")

    calls = {"n": 0}

    def _fake_fetch(_url: str, **_kwargs) -> str:
        calls["n"] += 1
        return RAW_TWO

    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", _fake_fetch)

    snap = fetch_catalog(group="active", cache_dir=tmp_path)
    assert calls["n"] == 1
    assert snap.from_cache is False
    assert snap.parsed_count == 2
    # Old snapshot is kept, not deleted — the study needs the time series.
    assert stale.exists()
    assert len(snapshots(tmp_path)) == 2


def test_fetch_catalog_skips_checksum_failures_without_aborting(tmp_path, monkeypatch) -> None:
    bad_line1 = ISS_LINE1[:-1] + "8"  # real check digit is 7
    raw = "\r\n".join([ISS_NAME, ISS_LINE1, ISS_LINE2, "JUNKSAT", bad_line1, ISS_LINE2]) + "\r\n"
    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", lambda *_a, **_k: raw)

    snap = fetch_catalog(group="active", cache_dir=tmp_path)
    assert snap.parsed_count == 1
    assert snap.skipped_count == 1
    assert snap.objects[0].norad_id == 25544


def test_fetch_catalog_raises_on_celestrak_diagnostic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "prahari_orbital.ingest.fetch_gp_data",
        lambda *_a, **_k: "Invalid query: satellite group 'bogus' not found.",
    )
    with pytest.raises(RuntimeError, match="diagnostic"):
        fetch_catalog(group="bogus", cache_dir=tmp_path)


def test_fetch_catalog_falls_back_to_stale_cache_on_timeout(tmp_path, monkeypatch, caplog) -> None:
    # A cache file well outside the 6 h freshness window: the normal cache-hit
    # path is skipped, so fetch_catalog goes to the network, which times out.
    stale_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    stale = tmp_path / f"active_{_stamp(stale_ts)}.tle"
    stale.write_text(RAW_TWO, encoding="utf-8")

    def _timeout(*_args, **_kwargs) -> str:
        raise CatalogFetchError("CelesTrak fetch failed after 3 retries: Read timed out.")

    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", _timeout)

    with caplog.at_level(logging.WARNING, logger="prahari_orbital.ingest"):
        snap = fetch_catalog(group="active", cache_dir=tmp_path)

    # The stale cache file was used instead of aborting.
    assert snap.from_cache is True
    assert snap.source_path == stale
    assert snap.fetched_at == stale_ts
    assert snap.parsed_count == 2
    # A clear warning naming the staleness was logged.
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("STALE" in m and "freshness window" in m for m in warnings)


def test_fetch_catalog_reraises_timeout_when_no_cache_exists(tmp_path, monkeypatch) -> None:
    def _timeout(*_args, **_kwargs) -> str:
        raise CatalogFetchError("CelesTrak fetch failed after 3 retries: Connection refused.")

    monkeypatch.setattr("prahari_orbital.ingest.fetch_gp_data", _timeout)

    with pytest.raises(CatalogFetchError, match="no cached snapshot|no cache"):
        fetch_catalog(group="active", cache_dir=tmp_path)
