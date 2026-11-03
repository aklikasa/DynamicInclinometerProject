# V0.5.3 changes

- Fix actual MCU raw capture blocked on `ACC_FS=0` / `GYRO_FS=0`.
- Preserve real int16 values without silently using default g / dps conversion.
- Optional clearly tagged `CAL_FILE_UNVERIFIED` conversion after UID-based calibration file matching and operator approval.
- Live IMU preview (only when idle) and separate corrected/uncorrected CSV columns.
- Timed/manual-start-stop acquisition; manifest persisted on cancellation and failure.
- Separate calibration folder selector, UID-specific two-JSON matching, file SHA256 provenance.
- CT-05 window can auto-suggest matching ACC JSON via capability interface; it still forbids uncertain scale for accuracy acceptance.
- Fix stretched DockPanel motor control buttons; preserve original vendor DLL / real turntable logic.
- Add self-tests for unknown FS, true FS, UID file matches/mismatch and correction matrix application.

No Windows executable or hardware acceptance has been claimed; code must be built and verified in a Windows .NET 10 environment.
