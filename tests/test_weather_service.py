import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weather_service import fetch_metars, fetch_and_store


class WeatherServiceTests(unittest.TestCase):
    def make_mock_response(self, response_data, url="https://aviationweather.gov/api/data/metar?ids=KBFI%2CKRNT&format=json"):
        class MockResponse:
            def __init__(self, data, url):
                self._data = data
                self.url = url

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        return MockResponse(response_data, url)

    @patch("weather_service.requests.get")
    def test_fetch_metars_parses_metar_and_altimeter(self, mock_get):
        sample = [
            {
                "icaoId": "KBFI",
                "rawOb": "METAR KBFI 072253Z 00000KT 9SM FU CLR 29/12 A3003 RMK AO2 SLP170 T02890122",
            },
            {
                "icaoId": "KRNT",
                "rawOb": "METAR KRNT 072253Z 36007KT 7SM FU CLR 29/13 A3004 RMK AO2 SLP176 T02890133",
            },
        ]
        mock_get.return_value = self.make_mock_response(sample)

        result = fetch_metars(["KBFI", "KRNT"])

        self.assertIn("KBFI", result["stations"])
        self.assertIn("KRNT", result["stations"])
        self.assertEqual(result["stations"]["KBFI"]["altimeter"], 30.03)
        self.assertEqual(result["stations"]["KRNT"]["altimeter"], 30.04)
        self.assertEqual(result["stations"]["KBFI"]["metar"], sample[0]["rawOb"])
        self.assertEqual(result["stations"]["KBFI"]["observation_time"], "2253Z")
        self.assertEqual(result["stations"]["KRNT"]["observation_time"], "2253Z")
        self.assertNotIn("rawOb", result["stations"]["KBFI"])
        self.assertNotIn("rawOb", result["stations"]["KRNT"])
        self.assertEqual(result["stations"]["KBFI"]["available"], 0)
        self.assertEqual(result["stations"]["KRNT"]["available"], 0)

    @patch("weather_service.requests.get")
    def test_fetch_and_store_writes_json_file(self, mock_get):
        sample = [
            {
                "icaoId": "KBFI",
                "rawOb": "METAR KBFI 072253Z 27030G35KT 0.75SM TSRA OVC008 A3003 RMK AO2 LTGICRA",
            }
        ]
        mock_get.return_value = self.make_mock_response(sample)

        with TemporaryDirectory() as out_dir:
            result = fetch_and_store(["KBFI"], out_dir=out_dir)
            self.assertIsNotNone(result.get("_stored_path"))
            stored_path = Path(result["_stored_path"])
            self.assertTrue(stored_path.exists())
            stored = json.loads(stored_path.read_text())
            self.assertEqual(stored["stations"]["KBFI"]["altimeter"], 30.03)
            self.assertEqual(stored["stations"]["KBFI"]["metar"], sample[0]["rawOb"])
            self.assertEqual(stored["stations"]["KBFI"]["lightning"], 1)
            self.assertEqual(stored["stations"]["KBFI"]["windspeed_25kts"], 1)
            self.assertEqual(stored["stations"]["KBFI"]["windgusts_25kts"], 1)
            self.assertEqual(stored["stations"]["KBFI"]["low_visibility"], 1)
            self.assertFalse(stored["stations"]["KBFI"]["available"])


if __name__ == "__main__":
    unittest.main()
