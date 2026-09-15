"""Tests for fns_api.py — QR parsing and helper functions."""

import pytest
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fns_api
from fns_api import _parse_qr_datetime, _split_qr_query, qr_to_params, _describe_exception


# ---------------------------------------------------------------------------
# _parse_qr_datetime
# ---------------------------------------------------------------------------

class TestParseQrDatetime:
    @pytest.mark.parametrize("raw, expected", [
        # Compact format without seconds
        ("20250412T1942", datetime(2025, 4, 12, 19, 42, 0)),
        # Compact format with seconds
        ("20250412T194215", datetime(2025, 4, 12, 19, 42, 15)),
        # ISO with separators
        ("2025-04-12T19:42", datetime(2025, 4, 12, 19, 42, 0)),
        ("2025-04-12T19:42:15", datetime(2025, 4, 12, 19, 42, 15)),
        # With trailing Z
        ("20250412T1942Z", datetime(2025, 4, 12, 19, 42, 0)),
        ("2025-04-12T19:42:00Z", datetime(2025, 4, 12, 19, 42, 0)),
        # URL-encoded space (sometimes sent as '+')
        ("2025-04-12T19:42:00", datetime(2025, 4, 12, 19, 42, 0)),
        # Lowercase t separator (normalised to uppercase)
        ("20250412t1942", datetime(2025, 4, 12, 19, 42, 0)),
    ])
    def test_valid_timestamps(self, raw, expected):
        assert _parse_qr_datetime(raw) == expected

    @pytest.mark.parametrize("bad", [
        "",
        "not-a-date",
        "20250412",          # missing T and time
        "T1942",             # missing date
    ])
    def test_invalid_timestamps_raise(self, bad):
        with pytest.raises(ValueError):
            _parse_qr_datetime(bad)

    def test_url_encoded_plus_as_space(self):
        # '+' is URL-encoding for space; urllib.parse.unquote_plus converts it
        result = _parse_qr_datetime("2025-04-12T19%3A42%3A00")
        assert result == datetime(2025, 4, 12, 19, 42, 0)


# ---------------------------------------------------------------------------
# _split_qr_query
# ---------------------------------------------------------------------------

class TestSplitQrQuery:
    def test_plain_query_string(self):
        parts = _split_qr_query("t=20250412T1942&s=123.45&fn=1234567890&i=99&fp=111&n=1")
        assert parts["t"] == "20250412T1942"
        assert parts["s"] == "123.45"
        assert parts["fn"] == "1234567890"
        assert parts["n"] == "1"

    def test_full_url_strips_path(self):
        url = "https://qr.nalog.ru/check?t=20250412T1942&s=100.00&fn=9999&i=1&fp=2&n=1"
        parts = _split_qr_query(url)
        assert parts["t"] == "20250412T1942"
        assert parts["fn"] == "9999"

    def test_empty_string_returns_empty_dict(self):
        assert _split_qr_query("") == {}

    def test_keys_are_lowercased(self):
        parts = _split_qr_query("T=20250101T0000&S=0&FN=1&I=2&FP=3&N=1")
        assert "t" in parts
        assert "fn" in parts


# ---------------------------------------------------------------------------
# qr_to_params
# ---------------------------------------------------------------------------

class TestQrToParams:
    VALID_QR = "t=20250412T1942&s=199.99&fn=9876543210&i=12345&fp=67890&n=1"

    def test_valid_qr_returns_correct_params(self):
        params = qr_to_params(self.VALID_QR)
        assert params["Sum"] == 19999           # kopecks
        assert params["Date"] == "2025-04-12T19:42:00"
        assert params["Fn"] == "9876543210"
        assert params["FiscalDocumentId"] == 12345
        assert params["FiscalSign"] == "67890"
        assert params["TypeOperation"] == 1
        assert params["RawData"] is True

    def test_sum_rounded_to_kopecks(self):
        params = qr_to_params("t=20250101T0000&s=1.005&fn=1&i=1&fp=1&n=1")
        assert isinstance(params["Sum"], int)

    def test_missing_fn_raises(self):
        with pytest.raises(ValueError, match="fn"):
            qr_to_params("t=20250412T1942&s=10.00&i=1&fp=1&n=1")

    def test_missing_i_raises(self):
        with pytest.raises(ValueError, match="i"):
            qr_to_params("t=20250412T1942&s=10.00&fn=1&fp=1&n=1")

    def test_missing_fp_raises(self):
        with pytest.raises(ValueError, match="fp"):
            qr_to_params("t=20250412T1942&s=10.00&fn=1&i=1&n=1")

    def test_empty_qr_raises(self):
        with pytest.raises(ValueError):
            qr_to_params("")

    def test_bad_sum_raises(self):
        with pytest.raises(ValueError):
            qr_to_params("t=20250412T1942&s=abc&fn=1&i=1&fp=1&n=1")

    def test_default_type_operation_is_1(self):
        params = qr_to_params("t=20250412T1942&s=0&fn=1&i=1&fp=1")
        assert params["TypeOperation"] == 1

    def test_full_url_accepted(self):
        url = "https://qr.nalog.ru/check?t=20250412T1942&s=50.00&fn=111&i=2&fp=3&n=1"
        params = qr_to_params(url)
        assert params["Fn"] == "111"


# ---------------------------------------------------------------------------
# _describe_exception
# ---------------------------------------------------------------------------

class TestDescribeException:
    def test_exception_with_message(self):
        exc = ValueError("bad input")
        desc = _describe_exception(exc)
        assert "ValueError" in desc
        assert "bad input" in desc

    def test_exception_without_message(self):
        class BareError(Exception):
            def __str__(self):
                return "BareError"
        exc = BareError()
        desc = _describe_exception(exc)
        assert "BareError" in desc

    def test_runtime_error(self):
        exc = RuntimeError("HTTP 500: server error")
        desc = _describe_exception(exc)
        assert "RuntimeError" in desc
        assert "HTTP 500" in desc


class TestParseExpireTime:
    """Регрессия на реальную потерю запросов к ФНС.

    `datetime.fromisoformat(expires)` падал с `TypeError: fromisoformat: argument must be
    str`, когда ФНС отвечала без ExpireTime, и уносил с собой ВЕСЬ запрос чека — хотя токен
    приходил рабочий. На проде так потерялся 371 запрос (последний раз 30.06.2026): чек
    уходил в OCR-фолбэк и дальше на ручную проверку.
    """

    def test_parses_valid_timestamp(self):
        result = fns_api._parse_expire_time("2026-09-15T12:30:00")
        assert result == datetime(2026, 9, 15, 12, 30, 0)

    def test_strips_surrounding_whitespace(self):
        assert fns_api._parse_expire_time("  2026-09-15T12:30:00 ") == datetime(
            2026, 9, 15, 12, 30, 0
        )

    @pytest.mark.parametrize("value", [None, "", "   ", "не дата", 12345])
    def test_bad_value_does_not_raise(self, value):
        """Любой мусор вместо срока — токен всё равно считаем полученным."""
        assert fns_api._parse_expire_time(value) == datetime.min
