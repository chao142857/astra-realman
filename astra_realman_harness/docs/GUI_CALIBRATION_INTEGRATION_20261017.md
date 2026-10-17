# Four-camera GUI integration

Entry on yanglab: scripts/run_real_chunk_offline.py --port 8887 --live-cameras --three-calibration /home/tongji/alex/astra_onsite_1011/astra_realman_harness/config/engineering/three_camera_calibration_20261011.json

Mac forwarding: ssh -N -L 28886:127.0.0.1:8887 yanglab
GUI: http://127.0.0.1:28886/

Four live RGB streams verified available. Three-camera historical calibration is loaded in place with frozen SHA256 checking; new right-wrist calibration is loaded from the versioned JSON. GUI exposes parent frames, transforms, source hashes and validation limits. No image/video transfer or credential publishing. Previous 8886 service remains untouched.

30 real migration/calibration/HTTP tests passed on yanglab; 3 chunk DOM assertions passed locally. Local HTTP tests could not bind within the Mac sandbox; remote run passed. Browser inspection found and corrected live cameras incorrectly labeled DEMO.

This is observation/calibration plus fake action protocol integration, NOT a hardware executor certification. Model and robot commands remain disabled. Remaining acceptance: measured cross-base transform; reconcile historical TCP configuration; real collision/tracking/stop and gripper opening/contact feedback. Right-wrist heldout RMS 5.45 mm / max 9.97 mm and historical tabletop depth failures remain visible. No automatic identity transform or simulated base spacing is substituted.
