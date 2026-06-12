# BugCam Organization

A concise map of the `bugcam` package. Entry point: `bugcam = bugcam.cli:app` (Typer CLI).

## Layout

```
bugcam/
  cli.py                  CLI entry point; registers all subcommand groups
  __init__.py             Package version

  settings.yaml           Bundled operational defaults (capture/pipeline/detection/tracking)
  app_config.py           Settings resolver: merges settings.yaml + config.json + env + CLI
  config.py               Paths, env vars, and persistent device config (~/.config/bugcam/config.json)
  device_config.py        Typed device identity (DeviceConfig) loaded from config.json

  processing.py           Maps resolved settings -> the nested config the edge26 pipeline consumes
  runtime.py              Builds a configured Pipeline; resolves model/labels assets

  model_bundles.py        Resolve / list / download / cache detection model bundles
  model_bundle_publish.py Publish model bundles (maintainer tooling)
  environment_sensor.py   Read the SEN55 environment sensor
  s3_upload.py            Upload helper for results to S3
  utils.py                Small shared helpers

  commands/               One Typer module per CLI subcommand
    run.py                  All-in-one: record + process + upload + heartbeat + receiver
    process.py              Process existing media (no recording)
    record.py               Recording only
    receive.py              Run the DOT receiver server
    setup.py                Interactive device setup (writes config.json)
    status.py               Device/runtime status checks
    models.py               Manage model bundles
    upload.py               Upload watcher / one-shot upload
    heartbeat.py            Heartbeat snapshots
    environment.py          Environment sensor loop
    dot_info.py             DOT device info
    autostart.py            Install/manage the systemd service
    update.py               Self-update helper

  edge26/                 The capture -> detect -> classify pipeline
    main.py                 Pipeline orchestrator (recorder, detection, classification workers)
    queue.py                Disk-based classification FIFO queue
    capture/recorder.py     Camera capture + chunked video recording
    processing/processor.py Per-video frame processing: detection + tracking
    processing/classifier.py Hailo classification
    output/writer.py        Writes detection/classification results

  receiver/               Flask HTTP server receiving DOT track data
    __init__.py             create_app() factory
    config.py               Receiver host/port + timing constants
    routes.py               HTTP route handlers
    tracker.py              Pending-track finalization tracker

  sensors/sen55/          Vendored C driver + collector for the SEN55 sensor
```

## Configuration precedence

`bugcam run` / `bugcam process` resolve settings via `app_config.load_app_config`, low to high:

```
bundled settings.yaml
  < ~/.config/bugcam/config.json   (device identity + paths, written by `bugcam setup`)
  < --settings <file>              (user overrides)
  < BUGCAM_* environment variables
  < explicit CLI flags
```

`settings.yaml` holds only operational defaults; device identity, credentials, and
storage paths live in `config.json` (managed by `bugcam setup`).

## Runtime data flow

```
recorder (capture/recorder.py)
  -> video chunks on disk
  -> detection worker (edge26/main.py + processing/processor.py): motion detect + track
  -> crops queued (edge26/queue.py)
  -> classifier (processing/classifier.py): Hailo inference
  -> writer (output/writer.py): results on disk
  -> upload watcher (commands/upload.py): push to S3 / backend
```

The DOT `receiver/` runs alongside as a separate Flask server, ingesting track
telemetry from iOS devices into the same input storage the pipeline processes.
