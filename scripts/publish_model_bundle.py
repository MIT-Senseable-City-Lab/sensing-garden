#!/usr/bin/env python3
"""Publish a BugCam model bundle to S3."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bugcam.model_bundle_publish import (
    DEFAULT_MODELS_BUCKET,
    format_bundle_publish_summary,
    publish_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload a model bundle to S3 without deleting legacy flat objects.",
    )
    parser.add_argument("--bundle-name", required=True, help="Public bundle name, e.g. london_141-multitask")
    parser.add_argument("--model-file", required=True, type=Path, help="Local HEF file to publish as model.hef")
    parser.add_argument("--labels-file", required=True, type=Path, help="Local labels.txt file")
    parser.add_argument("--bucket", default=DEFAULT_MODELS_BUCKET, help="S3 bucket name")
    parser.add_argument("--prefix", default="", help="Optional S3 key prefix")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing bundle objects if present")
    parser.add_argument("--skip-verify", action="store_true", help="Skip post-upload HEAD verification")
    parser.add_argument("--dry-run", action="store_true", help="Print the bundle keys without uploading")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        keys = publish_bundle(
            bundle_name=args.bundle_name,
            model_path=args.model_file,
            labels_path=args.labels_file,
            bucket=args.bucket,
            prefix=args.prefix,
            overwrite=args.overwrite,
            verify=not args.skip_verify,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    action = "Planned" if args.dry_run else "Published"
    print(f"{action} bundle '{args.bundle_name}' to bucket '{args.bucket}'.")
    print(format_bundle_publish_summary(args.bucket, keys))
    print("Legacy flat .hef objects are untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
