# Model Bundle Cutover

This runbook covers the production cut from flat S3 model files to BugCam model bundles.

## Target Contract

Each public model is a bundle folder in the models bucket:

- `<bundle>/model.hef`
- `<bundle>/labels.txt`

Example:

- `london_141-multitask/model.hef`
- `london_141-multitask/labels.txt`

Legacy flat `.hef` objects should remain in the bucket during the cut for rollback safety.

## 1. Publish Bundle Objects

Use the publishing helper from the BugCam repo:

```bash
python scripts/publish_model_bundle.py \
  --bundle-name london_141-multitask \
  --model-file /path/to/london_141-multitask.hef \
  --labels-file /path/to/labels.txt \
  --dry-run
```

Then run the real upload:

```bash
python scripts/publish_model_bundle.py \
  --bundle-name london_141-multitask \
  --model-file /path/to/london_141-multitask.hef \
  --labels-file /path/to/labels.txt
```

The script does not delete or replace the old flat `.hef` objects unless `--overwrite` is explicitly used.

## 2. Deploy BugCam

Deploy the `bugcam-cli` build that expects bundle-based model installs.

After this deploy, the supported model contract is:

```bash
bugcam models download <bundle-name>
```

## 3. Validate Target Runtime

On the target Pi/runtime, verify:

```bash
bugcam models download london_141-multitask
bugcam status jobs
```

`bugcam status jobs` should show:

- `bugspot=ok`
- `classification=off` for the default detection-only job path

If you intentionally enable classification with `BUGCAM_EDGE26_CLASSIFICATION=1`, then the same check should also show:

- `model=ok`
- `labels=ok`
- `hailo_platform=ok`

## 4. Smoke Test Processing

Run one real job through the queue:

- import or record one video
- process it through the jobs pipeline
- confirm local outputs exist
- confirm upload metadata still succeeds

This is the final go/no-go check.

## Rollback

Rollback is app-level:

- redeploy the previous BugCam build
- leave the new bundle folders in S3
- keep the legacy flat `.hef` objects until the new prod path is stable

## RPi5 Smoke Environment

For non-hardware Linux smoke tests on an arm64 machine:

```bash
./scripts/run_rpi5_smoke.sh
```

This uses Docker with an arm64 Bookworm-based image. It validates CLI/package behavior and the test suite, but it does not emulate Hailo hardware or Picamera2.
