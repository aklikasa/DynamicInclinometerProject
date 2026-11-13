# -*- coding: utf-8 -*-
"""Keep PCB identity inputs in step with the MCU-derived DTS serial number.

This helper has no Qt imports and does not talk to the serial port. The existing
GUI polling timer drives it with the result of the *existing* UID query.
"""
import re

_DTS_PATTERN = re.compile(r"DTS[0-9]{6}\Z")


class DeviceSnAutoFill:
    """Auto-fill multiple PCB serial fields without disturbing ongoing jobs.

    If the device has no readable UID, leave manually entered numbers alone.
    Clear only values that this controller itself populated when disconnecting.
    """

    def __init__(self):
        self._bindings = []

    def register(self, line_edit, is_busy=None):
        """Register a QLineEdit-like object and an optional active-job predicate."""
        if any(item['field'] is line_edit for item in self._bindings):
            return
        self._bindings.append({'field': line_edit, 'busy': is_busy, 'last_auto': ''})

    def update(self, device_sn):
        # Never propagate arbitrary/unverified strings from a stale data source.
        new_sn = str(device_sn or '').strip()
        if not _DTS_PATTERN.fullmatch(new_sn):
            new_sn = ''
        for item in self._bindings:
            if item['busy'] is not None and item['busy']():
                # A running calibration/recording owns its frozen PCB identifier.
                continue
            field = item['field']
            previous_auto_sn = item['last_auto']
            current = field.text().strip()
            if new_sn:
                # UID is the source of truth when supported; keep both pages equal.
                if current != new_sn:
                    field.setText(new_sn)
                item['last_auto'] = new_sn
            else:
                # Disconnect/old firmware: no UID warning, never delete manual IDs.
                if previous_auto_sn and current == previous_auto_sn:
                    field.clear()
                item['last_auto'] = ''
