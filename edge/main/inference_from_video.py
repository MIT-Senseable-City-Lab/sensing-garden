import cv2
import time
import os
import sys
import requests
import logging
import numpy as np
import threading
import queue
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
from models.object_detection_utils import ObjectDetectionUtils
from models.detection import run_inference
from models.classification import infer_image
from models.insect_tracker import InsectTracker
from sensing_garden_client import SensingGardenClient
import tempfile

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoInferenceProcessor:
    def __init__(self, class_names, families, genera, genus_to_family, species_to_genus,
                 model_path="weights/small-generic.hef", labels_path="data/labels.txt",
                 classification_model="weights/london_141-multitask.hef",
                 batch_size=1, confidence_threshold=0.35, enable_uploads=True, device_id="video_processor"):
        
        # Taxonomy data (now passed in)
        self.class_names = class_names
        self.families = families
        self.genera = genera
        self.genus_to_family = genus_to_family
        self.species_to_genus = species_to_genus
        
        # Model and processor configuration
        self.model_path = model_path
        self.labels_path = labels_path
        self.classification_model = classification_model
        self.batch_size = batch_size
        self.confidence_threshold = confidence_threshold
        self.device_id = device_id
        self.model_id = "london_141"
        self.enable_uploads = enable_uploads
        
        # Download weights if they don't exist
        self._ensure_weights_exist()
        
        # Store all detections for batch upload
        self.all_detections = []
        
        # Per-video frame count for logging/timestamps
        self.frame_count = 0
        
        self.det_utils = ObjectDetectionUtils(labels_path)
        
        if self.enable_uploads:
            self.sgc = self.initialize_sensing_garden_client()
        
    def _ensure_weights_exist(self):
        """Check if weight files exist and download them if they don't."""
        weights_info = [
            {
                'path': self.model_path,
                'url': 'https://github.com/aasehaa/sensing-garden/releases/download/weights/small-generic.hef'
            },
            {
                'path': self.classification_model,
                'url': 'https://github.com/aasehaa/sensing-garden/releases/download/weights/london_141-multitask.hef'
            }
        ]
        
        # Create weights directory if it doesn't exist
        weights_dir = os.path.dirname(self.model_path)
        if weights_dir and not os.path.exists(weights_dir):
            os.makedirs(weights_dir)
            print(f"Created directory: {weights_dir}")
        
        for weight_info in weights_info:
            weight_path = weight_info['path']
            weight_url = weight_info['url']
            
            if not os.path.exists(weight_path):
                print(f"Weight file not found: {weight_path}")
                print(f"Downloading from: {weight_url}")
                
                try:
                    response = requests.get(weight_url, stream=True)
                    response.raise_for_status()
                    
                    # Get file size for progress tracking
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with open(weight_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                
                                # Show progress every 10MB
                                if total_size > 0 and downloaded_size % (10 * 1024 * 1024) == 0:
                                    progress = (downloaded_size / total_size) * 100
                                    print(f"Download progress: {progress:.1f}% ({downloaded_size // (1024*1024)}MB/{total_size // (1024*1024)}MB)")
                    
                    print(f"Successfully downloaded: {weight_path}")
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"Failed to download {weight_path}: {e}")
                    raise RuntimeError(f"Could not download required weight file: {weight_path}")
                except Exception as e:
                    logger.error(f"Error downloading {weight_path}: {e}")
                    raise RuntimeError(f"Could not download required weight file: {weight_path}")
            else:
                print(f"Weight file found: {weight_path}")
    
    def initialize_sensing_garden_client(self):
        return SensingGardenClient(
            base_url=os.environ.get('API_BASE_URL'),
            api_key=os.environ.get('SENSING_GARDEN_API_KEY'),
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            aws_region=os.environ.get('AWS_REGION', 'us-east-1')
        )
    
    def convert_bbox_to_normalized(self, x, y, x2, y2, width, height):
        x_center = (x + x2) / 2.0 / width
        y_center = (y + y2) / 2.0 / height
        norm_width = (x2 - x) / width
        norm_height = (y2 - y) / height
        return [x_center, y_center, norm_width, norm_height]
    
    def find_closest_sen55_record(self, jsonl_path, target_ts):
        # Handles timestamps like "2025-08-01T09:08:51Z"
        target_dt = datetime.strptime(target_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        min_diff = None
        closest_record = None

        with open(jsonl_path, "r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    record_ts = datetime.strptime((obj["timestamp"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    diff = abs((record_ts - target_dt).total_seconds())
                    if (min_diff is None) or (diff < min_diff):
                        min_diff = diff
                        closest_record = obj
                except Exception as e:
                    continue  # skip malformed lines

        return closest_record

    # Example usage:
    #image_ts = "2025-08-01T09:25:48Z"  # timestamp of the image
    #match = find_closest_sen55_record("/home/sg/sensing-garden/sen55/env_data.jsonl", image_ts)
    #print(json.dumps(match, indent=2))

    
    def store_detection(self, frame, detection_data, timestamp, frame_time_seconds, sen55):
        """Stores detection for batch upload."""
        if not self.enable_uploads:
            print(f"📷 Detected (uploads disabled): {detection_data.get('species', 'N/A')} at {frame_time_seconds:.2f}s")
            sys.stdout.flush()
            return

        try:
            _, buffer = cv2.imencode('.jpg', frame)
            image_data = buffer.tobytes()

            logger.info('sen55 data: ', **sen55)

            payload = {
                "device_id": self.device_id,
                "model_id": self.model_id,
                "image_data": image_data,
                "timestamp": timestamp,
                "frame_time_seconds": frame_time_seconds,
                **detection_data,  # Unpacks family, genus, species, confidences, bbox, track_id
                **sen55, # unpacks sen55 data TODO: test if this is working
            }
            
            self.all_detections.append(payload)
            print(f"💿 Stored detection: {payload.get('species', 'N/A')} at {frame_time_seconds:.2f}s (total: {len(self.all_detections)})")
            sys.stdout.flush()

        except Exception as e:
            print(f"Error storing detection: {e}")

    def upload_all_detections(self):
        """Uploads all stored detections in batch."""
        if not self.enable_uploads or not self.all_detections:
            if self.enable_uploads:
                print("No detections to upload.")
            else:
                print("Uploads disabled - skipping upload.")
            return

        print(f"\n--- ☁️ Starting batch upload of {len(self.all_detections)} detections ---")
        
        failed_count = 0

        
        
        for i, payload in enumerate(self.all_detections):
            print("payload test nox index: ", payload.get("nox_index"))
            try:
                self.sgc.classifications.add(
                    device_id=payload['device_id'],
                    model_id=payload['model_id'],
                    image_data=payload['image_data'],
                    family=payload.get("family"),
                    genus=payload.get("genus"),
                    species=payload.get("species"),
                    family_confidence=payload.get("family_confidence"),
                    genus_confidence=payload.get("genus_confidence"),
                    species_confidence=payload.get("species_confidence"),
                    timestamp=payload['timestamp'],
                    bounding_box=payload.get('bbox'), 
                    environment={
                        "pm1p0": payload.get("pm1p0"),              # PM1.0 particulate matter (μg/m³)
                        "pm2p5": payload.get("pm2p5"),              # PM2.5 particulate matter (μg/m³)
                        "pm4p0": payload.get("pm4p0"),              # PM4.0 particulate matter (μg/m³)
                        "pm10p0": payload.get("pm10p0"),             # PM10.0 particulate matter (μg/m³)
                        "ambient_temperature": payload.get("ambient_temperature"), # Temperature (°C)
                        "ambient_humidity": payload.get("ambient_humidity"),    # Relative humidity (%)
                        "voc_index": payload.get("voc_index"),           # Volatile Organic Compounds index (integer)
                        "nox_index": payload.get("nox_index")             # Nitrogen Oxides index (integer)
                    },
                    track_id=str(payload['track_id'])
                )
                print(f"  ✓ [{i+1}/{len(self.all_detections)}] Uploaded: {payload.get('species', 'N/A')} at {payload.get('frame_time_seconds', 0):.2f}s")
                sys.stdout.flush()
            except Exception as e:
                print(f"  ✗ [{i+1}/{len(self.all_detections)}] Error uploading detection: {e}")
                failed_count += 1
                
        success_count = len(self.all_detections) - failed_count
        print(f"--- ☁️ Batch upload complete. {success_count} successful, {failed_count} failed. ---\n")

    def process_classification_results(self, classification_results, detection_data):
        for stream_name, result in classification_results.items():
            max_prob = np.max(result)
            top_indices = np.where(result >= (max_prob - 0.01))[0]
            
            if result.shape == (141,):  # Species
                detection_data["species"] = " | ".join([
                    self.class_names[idx] if idx < len(self.class_names) else f"Species {idx}" 
                    for idx in top_indices
                ])
                detection_data["species_confidence"] = float(max_prob)
            elif result.shape == (114,):  # Genus
                detection_data["genus"] = " | ".join([
                    self.genera[idx] if idx < len(self.genera) else f"Genus {idx}" 
                    for idx in top_indices
                ])
                detection_data["genus_confidence"] = float(max_prob)
            elif result.shape == (40,):  # Family
                detection_data["family"] = " | ".join([
                    self.families[idx] if idx < len(self.families) else f"Family {idx}" 
                    for idx in top_indices
                ])
                detection_data["family_confidence"] = float(max_prob)
        
        return detection_data
    
    def process_frame(self, frame, frame_time_seconds, tracker, global_frame_count, show_boxes=False):
        """Process a single frame from the video."""
        # Increment per-video frame counter for logging
        self.frame_count += 1
        
        # Convert BGR to RGB for inference
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        infer_results = run_inference(
            net=self.model_path,
            input=rgb_frame,
            batch_size=self.batch_size,
            labels=self.labels_path,
            save_stream_output=False
        )
        
        if show_boxes:
            print(f"Frame {self.frame_count} ({frame_time_seconds:.2f}s): Found {len(infer_results)} raw detections")
        
        # First pass: collect all valid detections for tracking
        valid_detections = []
        valid_detection_data = []
        
        if len(infer_results) > 0:
            height, width = frame.shape[:2]
            
            for detection in infer_results:
                if len(detection) != 5:
                    continue
                    
                y_min, x_min, y_max, x_max, confidence = detection
                
                if confidence < self.confidence_threshold:
                    continue
                
                # Convert to pixel coordinates
                x, y = int(x_min * width), int(y_min * height)
                x2, y2 = int(x_max * width), int(y_max * height)
                
                # Clamp coordinates
                x, y, x2, y2 = max(0, x), max(0, y), min(width, x2), min(height, y2)
                
                if x2 <= x or y2 <= y:
                    continue
                
                # Store detection for tracking (x1, y1, x2, y2 format)
                valid_detections.append([x, y, x2, y2])
                valid_detection_data.append({
                    'detection': detection,
                    'x': x, 'y': y, 'x2': x2, 'y2': y2,
                    'confidence': confidence
                })
        
        # Update tracker with detections using the global frame count
        track_ids = tracker.update(valid_detections, global_frame_count)
        
        if show_boxes and len(valid_detections) > 0:
            print(f"Frame {self.frame_count}: {len(valid_detections)} detections → {len(tracker.current_tracks)} active tracks")
        
        # Process each detection with its track ID
        for i, det_data in enumerate(valid_detection_data):
            x, y, x2, y2 = det_data['x'], det_data['y'], det_data['x2'], det_data['y2']
            confidence = det_data['confidence']
            track_id = track_ids[i] if i < len(track_ids) else None
            
            # Draw bounding box and track ID if showing boxes
            if show_boxes:
                cv2.rectangle(frame, (x, y), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{confidence:.2f}", (x, y - 10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                if track_id is not None:
                    cv2.putText(frame, f"ID:{track_id}", (x, y - 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            # Perform classification on the RGB frame crop
            cropped_region = cv2.resize(rgb_frame[y:y2, x:x2], (224, 224))
            classification_results = infer_image(cropped_region, hef_path=self.classification_model)
            
            detection_data = {
                "family": None, "genus": None, "species": None,
                "family_confidence": None, "genus_confidence": None, "species_confidence": None,
                "bbox": self.convert_bbox_to_normalized(x, y, x2, y2, width, height),
                "track_id": track_id
            }
            
            detection_data = self.process_classification_results(classification_results, detection_data)
            
            if show_boxes:
                if detection_data["species"]:
                    cv2.putText(frame, f"Species: {detection_data['species']}", (x, y2 + 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                if detection_data["genus"]:
                    cv2.putText(frame, f"Genus: {detection_data['genus']}", (x, y2 + 40), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                if detection_data["family"]:
                    cv2.putText(frame, f"Family: {detection_data['family']}", (x, y2 + 60), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
            
            timestamp = datetime.now().isoformat()

            # find closes environmental recording for the detection
            sen55 = self.find_closest_sen55_record("/home/sg/sensing-garden/sen55/env_data.jsonl", timestamp) # fetching closest environmental datapoint of detection
            
            # ex sen55: {"device_id":"sensor-123","timestamp":"2025-09-02T11:33:28Z","data":{"pm1p0":0.600000023841858,"pm2p5":0.699999988079071,"pm4p0":0.699999988079071,"pm10p0":0.699999988,"ambient_humidity":54.229999542236328,"ambient_temperature":25.395000457763672,"voc_index":107,"nox_index":1}}>
            self.store_detection(frame, detection_data, timestamp, frame_time_seconds, sen55)
        
        return frame

def process_video(video_path, processor, tracker, start_frame_count, show_video=False, output_video_path=None):
    """Process an MP4 video file frame by frame."""
    
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"Processing video: {video_path}")
    print(f"Video properties: {total_frames} frames, {fps:.2f} FPS, {duration:.2f}s duration")
    
    # Set up output video writer if requested
    out = None
    if output_video_path:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
        print(f"Output video will be saved to: {output_video_path}")
    
    frame_number = 0
    start_time = time.time()
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_time_seconds = frame_number / fps if fps > 0 else 0
            
            # Process the frame, passing the shared tracker and the correct global frame count
            global_frame_for_this_video = start_frame_count + frame_number
            processed_frame = processor.process_frame(frame, frame_time_seconds, tracker, global_frame_for_this_video, show_boxes=show_video)
            
            # Write to output video if requested
            if out:
                out.write(processed_frame)
            
            # Show video if requested
            if show_video:
                cv2.imshow('Video Inference', processed_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("User requested quit")
                    break
            
            frame_number += 1
            
            # Progress update every 100 frames
            if frame_number % 100 == 0:
                progress = (frame_number / total_frames) * 100
                elapsed = time.time() - start_time
                estimated_total = (elapsed / frame_number) * total_frames if frame_number > 0 else 0
                remaining = estimated_total - elapsed
                print(f"Progress: {frame_number}/{total_frames} ({progress:.1f}%) - "
                      f"ETA: {remaining:.1f}s")
    
    finally:
        cap.release()
        if out:
            out.release()
        if show_video:
            cv2.destroyAllWindows()
    
    processing_time = time.time() - start_time
    print(f"\nProcessing complete!")
    print(f"Processed {frame_number} frames in {processing_time:.2f}s")
    print(f"Average processing speed: {frame_number/processing_time:.2f} FPS")
    print(f"Total detections found: {len(processor.all_detections)}")
    return frame_number 