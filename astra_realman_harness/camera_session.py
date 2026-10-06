"""Persistent RGB streams with concurrent latest-frame buffers, no device resets/settings.

Structure follows DP MultiRealsense/SingleRealsense's persistent producers and latest
reads. The existing classes are not imported: SingleRealsense.run sets device
options and can load advanced configuration. This adapter uses neither operation.
"""
import copy
import threading
import time
import uuid

class CameraSession:
    def __init__(self, configs, rs_module=None, startup_timeout=15, snapshot_timeout=5, required_serials=None):
        self.configs = list(configs)
        self.required_serials = {c['serial'] for c in configs} if required_serials is None else set(required_serials)
        if not self.required_serials.issubset({c['serial'] for c in configs}):raise ValueError('REQUIRED_CAMERA_UNKNOWN')
        self.rs = rs_module
        self.startup_timeout = startup_timeout
        self.snapshot_timeout = snapshot_timeout
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.latest, self.errors, self.starts, self.last_sequence = {}, {}, {}, {}
        self.active_stream_serials = set()
        self.threads = []
        self.session_id = uuid.uuid4().hex
        self.snapshot_count = 0
        self.enumeration = {
            "attempts": [], "timeout_s": self.startup_timeout,
            "retry_interval_s": .2, "complete": False, "elapsed_s": None,
            "expected_serials": [c["serial"] for c in self.configs],
        }
        self.frame_warmup = {"timeout_s": self.startup_timeout, "elapsed_s": None}

    def _enumerate_expected(self, context):
        """Wait only for SDK enumeration; no resets, options, or pipeline restarts."""
        started = time.monotonic()
        deadline = started + self.startup_timeout
        expected = {c["serial"] for c in self.configs}
        serials = set()
        while True:
            attempt = {"attempt": len(self.enumeration["attempts"]) + 1,
                       "started_at": time.time(), "elapsed_s": time.monotonic() - started}
            try:
                serials = {d.get_info(self.rs.camera_info.serial_number)
                           for d in context.query_devices()}
                attempt["error"] = None
            except Exception as exc:
                serials = set()
                attempt["error"] = type(exc).__name__ + ":" + str(exc)[:300]
            attempt.update(finished_at=time.time(), serials=sorted(serials),
                           missing_serials=sorted(expected - serials))
            self.enumeration["attempts"].append(attempt)
            if self.required_serials.issubset(serials):
                self.enumeration["complete"] = expected.issubset(serials)
                self.enumeration["required_complete"] = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.stop_event.wait(min(.2, remaining)):
                break
        self.enumeration["elapsed_s"] = time.monotonic() - started
        self.enumeration["final_serials"] = sorted(serials)
        self.enumeration["missing_serials"] = sorted(expected - serials)
        return serials

    def __enter__(self):
        if self.rs is None:
            import pyrealsense2
            self.rs = pyrealsense2
        context = self.rs.context()
        serials = self._enumerate_expected(context)
        warmup_started = time.monotonic()
        for config in self.configs:
            serial = config["serial"]
            if serial not in serials:
                self.errors[serial] = "SDK_SERIAL_NOT_FOUND"
                continue
            thread = threading.Thread(target=self._produce, args=(config, context),
                                      name="harness-camera-"+serial, daemon=True)
            thread.start()
            self.threads.append(thread)
        # Enumeration and frame warmup each have an explicit startup_timeout
        # budget. Enumeration never extends the warmup loop or retries a pipeline.
        deadline = warmup_started + self.startup_timeout
        with self.condition:
            while any(c["serial"] not in self.errors and
                      self.latest.get(c["serial"], {}).get("sequence", 0) < 5 for c in self.configs if c["serial"] in self.required_serials):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    for c in self.configs:
                        if c["serial"] in self.required_serials and c["serial"] not in self.errors and self.latest.get(c["serial"], {}).get("sequence", 0) < 5:
                            self.errors[c["serial"]] = "CAMERA_STARTUP_TIMEOUT"
                    break
                self.condition.wait(min(remaining, .2))
        self.frame_warmup["elapsed_s"] = time.monotonic() - warmup_started
        return self

    def _produce(self, config, context):
        rs = self.rs
        serial = config["serial"]
        pipeline = rs.pipeline(context)
        started = False
        try:
            settings = rs.config()
            settings.enable_device(serial)
            settings.enable_stream(rs.stream.color, config["width"], config["height"],
                                   rs.format.rgb8, config["fps"])
            pipeline.start(settings)
            started = True
            with self.condition:
                self.starts[serial] = self.starts.get(serial, 0) + 1
                self.active_stream_serials.add(serial)
            sequence = 0
            while not self.stop_event.is_set():
                frames = pipeline.wait_for_frames(1000)
                received, monotonic = time.time(), time.monotonic()
                frame = frames.get_color_frame()
                if not frame:
                    raise RuntimeError("NO_COLOR_FRAME")
                sequence += 1
                intr = frame.profile.as_video_stream_profile().get_intrinsics()
                item = {
                    "serial": serial, "role": config.get("role", "unassigned"),
                    "role_confirmed": config.get("role_confirmed", False),
                    "host_received_at": received, "host_received_monotonic": monotonic,
                    "device_timestamp_ms": frame.get_timestamp(),
                    "device_timestamp_domain": str(frame.get_frame_timestamp_domain()),
                    "frame_number": frame.get_frame_number(), "sequence": sequence,
                    "encoding": "RGB8", "shape": [intr.height, intr.width, 3],
                    "intrinsics": {"source": "device_factory_color_intrinsics",
                                   "fx": intr.fx, "fy": intr.fy, "cx": intr.ppx, "cy": intr.ppy,
                                   "distortion_model": str(intr.model), "coeffs": list(intr.coeffs)},
                    "extrinsics": None, "optical_frame_convention": "x right, y down, z forward",
                    "base_transform_status": "UNCONFIRMED",
                    "_pixels": bytes(frame.get_data()), "_stride": frame.get_stride_in_bytes(),
                }
                with self.condition:
                    self.latest[serial] = item
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.errors[serial] = type(exc).__name__ + ":" + str(exc)[:300]
                self.condition.notify_all()
        finally:
            if started:
                try:pipeline.stop()  # Release only the stream owned by this session.
                finally:
                    with self.condition:self.active_stream_serials.discard(serial)

    def stream_metrics(self, configs=None):
        with self.condition:
            return {'model_input_serials':[c['serial'] for c in (self.configs if configs is None else configs)],
                    'active_stream_serials':sorted(self.active_stream_serials),
                    'pipeline_start_count':dict(self.starts)}

    def snapshot(self, run, configs=None):
        from observation import png_rgb
        configs = self.configs if configs is None else list(configs)
        known = {c["serial"]: c for c in self.configs}
        if any(c != known.get(c["serial"]) for c in configs):
            raise ValueError("UNKNOWN_CAMERA_CONFIGURATION")
        requested = {c["serial"] for c in configs}
        deadline = time.monotonic() + self.snapshot_timeout
        with self.condition:
            while True:
                ready = all(c["serial"] in self.errors or
                            (self.latest.get(c["serial"], {}).get("sequence", 0) >
                             self.last_sequence.get(c["serial"], 0) and
                             time.monotonic()-self.latest[c["serial"]]["host_received_monotonic"] < .5)
                            for c in configs)
                if ready or time.monotonic() >= deadline:
                    break
                self.condition.wait(.02)
            selected = [dict(self.latest[c["serial"]]) for c in configs
                        if c["serial"] in self.latest and c["serial"] not in self.errors]
            failures = [{"device": s, "message": e} for s, e in self.errors.items() if s in requested]
            for c in configs:
                s = c["serial"]
                item = self.latest.get(s)
                if s not in self.errors and (not item or
                        item["sequence"] <= self.last_sequence.get(s, 0) or
                        time.monotonic()-item["host_received_monotonic"] >= .5):
                    failures.append({"device": s, "message": "CAMERA_LATEST_FRAME_TIMEOUT"})
                    selected = [x for x in selected if x["serial"] != s]
            for item in selected:
                self.last_sequence[item["serial"]] = item["sequence"]
        # Never subtract independent hardware clock epochs; require host-mapped SDK timestamps.
        comparable = bool(selected) and all(x["device_timestamp_domain"] in
            ("timestamp_domain.global_time", "timestamp_domain.system_time") for x in selected)
        for item in selected:
            item["captured_at"] = item["device_timestamp_ms"]/1000 if comparable else item["host_received_at"]
            item["timestamp_basis"] = "sdk_host_time" if comparable else "host_receive_time_fallback"
            path = run / ("camera-" + item["serial"] + ".png")
            h, w, _ = item["shape"]
            item["sha256"] = png_rgb(path, w, h, item.pop("_pixels"), item.pop("_stride"))
            item["image_path"] = str(path)
        times = [x["captured_at"] for x in selected]
        self.snapshot_count += 1
        metrics = {
            "capture_span_ms": (max(times)-min(times))*1000 if times else None,
            "timestamp_basis": "sdk_host_time" if comparable else "host_receive_time_fallback",
            "timestamp_semantics_confirmed": comparable,
            "hardware_synchronized": False, "camera_session_id": self.session_id,
            "observation_index": self.snapshot_count,
            **self.stream_metrics(configs),
            "expected_serials": [c["serial"] for c in configs],
            "device_enumeration": copy.deepcopy(self.enumeration),
            "frame_warmup": dict(self.frame_warmup),
            "startup_wait_budget_s": 2 * self.startup_timeout,
        }
        return selected, failures, metrics

    def __exit__(self, *args):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(2)
