"""
Unit and integration tests for SecureLink battery telemetry, LiPo discharge estimation,
floating-pin detection, and USB heartbeat parsing.
"""

import unittest
from securelinkdb.usb_manager import (
    calculate_lipo_percentage,
    USBDeviceManager,
    LIPO_DISCHARGE_TABLE,
)


class TestLiPoCurveEstimation(unittest.TestCase):
    """Verifies calibrated non-linear 1S LiPo voltage to percentage mapping."""

    def test_maximum_voltage_saturation(self):
        self.assertEqual(calculate_lipo_percentage(4200), 100)
        self.assertEqual(calculate_lipo_percentage(4300), 100)
        self.assertEqual(calculate_lipo_percentage(4400), 100)

    def test_minimum_cutoff_voltage(self):
        self.assertEqual(calculate_lipo_percentage(3270), 0)
        self.assertEqual(calculate_lipo_percentage(3200), 0)
        self.assertEqual(calculate_lipo_percentage(2900), 0)

    def test_nominal_curve_interpolation(self):
        # Exact table points
        self.assertEqual(calculate_lipo_percentage(4080), 85)
        self.assertEqual(calculate_lipo_percentage(3850), 55)
        self.assertEqual(calculate_lipo_percentage(3750), 25)

        # Midpoint interpolations
        pct_3965 = calculate_lipo_percentage(3965)
        self.assertTrue(70 <= pct_3965 <= 75)

        pct_3830 = calculate_lipo_percentage(3830)
        self.assertTrue(45 <= pct_3830 <= 50)

    def test_floating_pin_and_out_of_bounds_detection(self):
        # Floating pin reading (< 2800mV)
        self.assertEqual(calculate_lipo_percentage(0), -1)
        self.assertEqual(calculate_lipo_percentage(150), -1)
        self.assertEqual(calculate_lipo_percentage(1200), -1)
        self.assertEqual(calculate_lipo_percentage(2799), -1)

        # Over-voltage / faulty sensor reading (> 4400mV)
        self.assertEqual(calculate_lipo_percentage(4401), -1)
        self.assertEqual(calculate_lipo_percentage(5000), -1)


class TestUSBManagerBatteryHeartbeat(unittest.TestCase):
    """Verifies USBManager PING protocol handling, battery validation, and telemetry state."""

    def setUp(self):
        self.mgr = USBDeviceManager(verify_credential_fn=lambda dev_id: True)
        self.mgr.device_id = "PIN-F360"
        self.mgr.is_authenticated = True

    def test_unconfigured_sensor_ping(self):
        # Firmware reports -1 when no external voltage divider is present
        self.mgr._handle_command("SL:PING:-1:-1:VAD ARMED")
        self.assertEqual(self.mgr.battery, -1)
        self.assertEqual(self.mgr.battery_mv, -1)
        self.assertFalse(self.mgr.battery_valid)
        self.assertEqual(self.mgr.battery_status, "UNAVAILABLE")

    def test_floating_pin_voltage_rejection(self):
        # Firmware raw ADC reads 120mV noise without divider
        self.mgr._handle_command("SL:PING:0:120:VAD ARMED")
        self.assertEqual(self.mgr.battery, -1)
        self.assertEqual(self.mgr.battery_mv, -1)
        self.assertFalse(self.mgr.battery_valid)
        self.assertEqual(self.mgr.battery_status, "UNAVAILABLE")

    def test_valid_calibrated_battery_telemetry(self):
        # Physical pin connected with voltage divider at 3980mV (75%)
        self.mgr._handle_command("SL:PING:75:3980:VAD ARMED")
        self.assertEqual(self.mgr.battery, 75)
        self.assertEqual(self.mgr.battery_mv, 3980)
        self.assertTrue(self.mgr.battery_valid)
        self.assertEqual(self.mgr.battery_status, "VALID")

    def test_voltage_provided_with_uncomputed_pct(self):
        # Pin provides valid millivolts (3850mV) with -1 pct
        self.mgr._handle_command("SL:PING:-1:3850:VAD ARMED")
        self.assertEqual(self.mgr.battery, 55)
        self.assertEqual(self.mgr.battery_mv, 3850)
        self.assertTrue(self.mgr.battery_valid)
        self.assertEqual(self.mgr.battery_status, "VALID")

    def test_device_update_payload_formatting(self):
        updates = []
        self.mgr.on_device_update = lambda d: updates.append(d)

        # 1. Unconfigured sensor
        self.mgr._handle_command("SL:PING:-1:-1:VAD ARMED")
        self.assertTrue(len(updates) > 0)
        latest = updates[-1]
        self.assertEqual(latest["battery"], -1)
        self.assertEqual(latest["batteryMv"], -1)
        self.assertFalse(latest["battery_valid"])
        self.assertEqual(latest["battery_status"], "UNAVAILABLE")
        self.assertEqual(latest["estRuntime"], "--")

        # 2. Valid battery reading
        self.mgr._handle_command("SL:PING:80:4020:VAD ARMED")
        latest = updates[-1]
        self.assertEqual(latest["battery"], 80)
        self.assertEqual(latest["batteryMv"], 4020)
        self.assertTrue(latest["battery_valid"])
        self.assertEqual(latest["battery_status"], "VALID")
        self.assertNotEqual(latest["estRuntime"], "--")

    def test_get_status_diagnostics(self):
        self.mgr._handle_command("SL:PING:-1:-1:VAD ARMED")
        st = self.mgr.get_status()
        self.assertEqual(st["battery"], -1)
        self.assertEqual(st["battery_mv"], -1)
        self.assertFalse(st["battery_valid"])
        self.assertEqual(st["battery_status"], "UNAVAILABLE")


class TestDashboardFallbackHandling(unittest.TestCase):
    """Verifies that missing battery telemetry maps to UNAVAILABLE without fabricating values."""

    def test_missing_sensor_status_code(self):
        mgr = USBDeviceManager()
        self.assertEqual(mgr.battery_status, "UNAVAILABLE")
        self.assertFalse(mgr.battery_valid)
        self.assertEqual(mgr.battery, -1)
        self.assertEqual(mgr.battery_mv, -1)

    def test_dashboard_json_payload_contract(self):
        mgr = USBDeviceManager()
        mgr.device_id = "PIN-F360"
        mgr.is_authenticated = True
        status = mgr.get_status()
        self.assertEqual(status["battery"], -1)
        self.assertEqual(status["battery_mv"], -1)
        self.assertEqual(status["battery_status"], "UNAVAILABLE")
        self.assertFalse(status["battery_valid"])

    def test_no_fabricated_reading_when_speech_or_uptime_active(self):
        mgr = USBDeviceManager()
        mgr.device_id = "PIN-F360"
        mgr.is_authenticated = True
        mgr.audio_streaming = True
        mgr.vad_state = "SPEECH DETECTED"
        # Audio or VAD activity must NEVER substitute or invent a battery percentage
        self.assertEqual(mgr.battery, -1)
        self.assertEqual(mgr.battery_mv, -1)
        self.assertEqual(mgr.battery_status, "UNAVAILABLE")
        self.assertFalse(mgr.battery_valid)


if __name__ == "__main__":
    unittest.main()
