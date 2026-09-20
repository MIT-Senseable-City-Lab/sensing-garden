"""
AE shutter cap via the rpi.agc exposure-mode table.

The Raspberry Pi AGC (auto-exposure) walks a paired (shutter, gain) candidate
table stored in the sensor tuning file; its maximum shutter is the last
shutter entry of the active exposure mode. Capping that entry is the only
libcamera mechanism that keeps AE fully automatic while guaranteeing the
shutter never gets slower than a configured value:

    - bright scene  -> AE picks a short shutter at minimum gain (unchanged)
    - dimming scene -> AE raises the shutter up to the cap, then raises gain
    - darker still  -> shutter stays pinned at the cap, gain keeps climbing,
                       and beyond the gain ceiling frames legitimately darken

The libcamera `ExposureTime` control does NOT do this: picamera2 turns a
non-zero value into ExposureTimeMode=Manual (pinning the shutter), and newer
libcamera ignores it entirely while AE runs. FrameDurationLimits is the frame
period (1/fps), not a shutter cap, so it cannot cap exposure below the frame
rate either. The exposure-mode table is the correct, version-stable lever.

The patched tuning is passed to Picamera2(tuning=...) at construction; any
failure (no camera, missing tuning file) degrades gracefully to the stock
tuning with a warning.
"""

import logging

logger = logging.getLogger(__name__)

# Stock sensors start their shutter ramp at 100 us.
DEFAULT_MIN_SHUTTER_US = 100
# imx708 (Camera Module 3) analogue gain ceiling, as used in the stock tables.
DEFAULT_MAX_GAIN = 16.0


def capped_exposure_mode(
    max_exposure_us: int,
    max_gain: float = DEFAULT_MAX_GAIN,
    min_shutter_us: int = DEFAULT_MIN_SHUTTER_US,
    gain_steps: tuple = (2.0, 4.0, 8.0, 16.0),
) -> dict:
    """Build an exposure-mode table whose shutter never exceeds max_exposure_us.

    Returns {"shutter": [...], "gain": [...]} with equal-length lists (the AGC
    requires shutter and gain to have the same number of entries): the shutter
    ramps from min_shutter_us up to the cap at minimum gain, then holds the cap
    while gain steps through ``gain_steps`` up to ``max_gain``.
    """
    cap = int(max_exposure_us)
    if cap <= 0:
        raise ValueError("max_exposure_us must be positive")
    if cap < min_shutter_us:
        raise ValueError(
            f"max_exposure_us {cap} us is below the sensor minimum shutter "
            f"{min_shutter_us} us"
        )

    ramp = sorted({int(round(x)) for x in (min_shutter_us, cap // 2, cap)})
    if ramp[0] < min_shutter_us:
        ramp[0] = min_shutter_us

    gains = [1.0] * len(ramp) + [float(g) for g in gain_steps]
    shutter = ramp + [cap] * len(gain_steps)

    if len(shutter) != len(gains):
        raise RuntimeError(
            f"internal table mismatch: {len(shutter)} shutter vs {len(gains)} gain entries"
        )
    if shutter[-1] != cap:
        raise RuntimeError("exposure table does not end on the requested cap")
    if max(gains) > max_gain:
        raise RuntimeError("exposure table gain exceeds the configured maximum")

    return {"shutter": shutter, "gain": gains}


def build_capped_tuning(
    max_exposure_us: int,
    max_gain: float = DEFAULT_MAX_GAIN,
) -> dict | None:
    """Return a patched sensor tuning dict capping the AE shutter, or None.

    Loads the stock tuning file for the first attached camera, caps the
    ``normal`` exposure mode of every AGC channel, and returns the modified
    dict for Picamera2(tuning=...). Any failure returns None so the caller can
    fall back to the stock tuning (record uncapped) with a warning.
    """
    if not max_exposure_us or max_exposure_us <= 0:
        return None
    try:
        from picamera2 import Picamera2

        cameras = Picamera2.global_camera_info()
        if not cameras:
            logger.warning("Exposure cap: no camera detected; recording uncapped")
            return None
        model = cameras[0]["Model"].strip()
        tuning = Picamera2.load_tuning_file(f"{model}.json")
        agc = Picamera2.find_tuning_algo(tuning, "rpi.agc")
        channels = agc.get("channels")
        if not channels:
            logger.warning(
                "Exposure cap: tuning for %s has no rpi.agc channels; recording uncapped",
                model,
            )
            return None

        mode = capped_exposure_mode(max_exposure_us, max_gain)
        patched = 0
        for channel in channels:
            exposure_modes = channel.get("exposure_modes", {})
            if "normal" not in exposure_modes:
                continue
            exposure_modes["normal"] = dict(mode)
            patched += 1
        if patched == 0:
            logger.warning(
                "Exposure cap: no normal exposure mode found in %s tuning; recording uncapped",
                model,
            )
            return None

        logger.info(
            "Exposure cap: capped %d AGC channel(s) in %s tuning at 1/%d s shutter",
            patched,
            model,
            max_exposure_us,
        )
        return tuning
    except Exception:
        logger.warning(
            "Exposure cap: could not build capped tuning; recording uncapped",
            exc_info=True,
        )
        return None
