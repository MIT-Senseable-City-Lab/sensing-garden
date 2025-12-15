"""Detection pipeline for bugcam.

This module requires system packages that cannot be pip-installed:
- PyGObject (gi): sudo apt install python3-gi python3-gi-cairo gir1.2-gstreamer-1.0
- Hailo SDK: sudo apt install hailo-all

For pipx users: pipx install bugcam --system-site-packages
"""

import os
import sys


def check_dependencies():
    """Check that required system dependencies are available."""
    missing = []

    try:
        import gi
    except ImportError:
        missing.append("PyGObject (gi)")

    try:
        import hailo
    except ImportError:
        missing.append("Hailo SDK")

    if missing:
        print("Error: Missing required system packages:", ", ".join(missing), file=sys.stderr)
        print(file=sys.stderr)
        print("On Raspberry Pi, install with:", file=sys.stderr)
        print("  sudo apt install python3-gi python3-gi-cairo gir1.2-gstreamer-1.0", file=sys.stderr)
        print("  sudo apt install hailo-all", file=sys.stderr)
        print(file=sys.stderr)
        print("For pipx users, reinstall with system packages access:", file=sys.stderr)
        print("  pipx uninstall bugcam", file=sys.stderr)
        print("  pipx install bugcam --system-site-packages", file=sys.stderr)
        sys.exit(1)


def main():
    """Run the detection pipeline."""
    # Check dependencies first
    check_dependencies()

    # Now safe to import - dependencies verified
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    import numpy as np
    import cv2
    import hailo

    from hailo_apps_infra.hailo_rpi_common import (
        get_caps_from_pad,
        get_numpy_from_buffer,
        app_callback_class,
    )
    from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

    # User-defined class to be used in the callback function
    class user_app_callback_class(app_callback_class):
        def __init__(self):
            super().__init__()
            self.new_variable = 42

        def new_function(self):
            return "The meaning of life is: "

    # Callback function that will be called when data is available from the pipeline
    def app_callback(pad, info, user_data):
        # Get the GstBuffer from the probe info
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        user_data.increment()
        string_to_print = f"Frame count: {user_data.get_count()}\n"

        # Get the caps from the pad
        format, width, height = get_caps_from_pad(pad)

        # Get video frame if enabled
        frame = None
        if user_data.use_frame and format is not None and width is not None and height is not None:
            frame = get_numpy_from_buffer(buffer, format, width, height)

        # Get the detections from the buffer
        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)

        # Parse the detections
        detection_count = 0
        for detection in detections:
            label = detection.get_label()
            bbox = detection.get_bbox()
            confidence = detection.get_confidence()
            if label == "person":
                track_id = 0
                track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
                if len(track) == 1:
                    track_id = track[0].get_id()
                string_to_print += f"Detection: ID: {track_id} Label: {label} Confidence: {confidence:.2f}\n"
                detection_count += 1

        if user_data.use_frame:
            cv2.putText(frame, f"Detections: {detection_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(frame, f"{user_data.new_function()} {user_data.new_variable}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            user_data.set_frame(frame)

        print(string_to_print)
        return Gst.PadProbeReturn.OK

    # Run the app
    user_data = user_app_callback_class()
    app = GStreamerDetectionApp(app_callback, user_data)
    app.run()


if __name__ == "__main__":
    main()
