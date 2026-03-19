from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

from .config import IdentityConfig

logger = logging.getLogger(__name__)


class OwnerIdentityManager:
    def __init__(self, config: IdentityConfig) -> None:
        self._config = config
        self._storage_dir = Path(config.storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._profile_path = self._storage_dir / "owner_profile.json"
        self._embedding_path = self._storage_dir / "owner_embedding.npy"
        self._pending_sync_path = self._storage_dir / "pending_sync.json"
        self._lock = threading.Lock()
        self._events: List[Dict[str, object]] = []
        self._cascade = None
        self._yunet = None
        self._sface = None
        self._embedding_backend = "face-hist-v1"
        self._owner_embedding = None
        self._owner_profile: Dict[str, object] = {}
        self._pending_sync: Dict[str, object] = {}
        self._last_tracking_bbox: Optional[Tuple[int, int, int, int]] = None
        self._last_recognition_label = "no_face"
        self._last_recognition_confidence = 0.0
        self._last_recognition_ts_ms = 0
        self._last_process_ms = 0
        self._enrollment: Dict[str, object] = {
            "active": False,
            "owner_label": "owner",
            "claim_token": "",
            "samples": [],
            "started_at_ms": 0,
            "last_sample_ms": 0,
            "last_bbox": None,
        }
        if cv2 is not None:
            try:
                self._cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("identity cascade init failed: %s", exc)
                self._cascade = None
        self._init_cv_models()
        self._load_state()

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    def _resolve_model_path(self, value: str) -> Path:
        raw = str(value or "").strip()
        path = Path(raw)
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[1] / path).resolve()
        return path

    def _init_cv_models(self) -> None:
        if cv2 is None:
            return
        detector_path = self._resolve_model_path(self._config.detector_model_path)
        recognizer_path = self._resolve_model_path(self._config.recognizer_model_path)
        if detector_path.exists():
            try:
                if hasattr(cv2, "FaceDetectorYN_create"):
                    self._yunet = cv2.FaceDetectorYN_create(str(detector_path), "", (320, 320))
                elif hasattr(cv2, "FaceDetectorYN") and hasattr(cv2.FaceDetectorYN, "create"):
                    self._yunet = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320))
            except Exception as exc:
                logger.warning("yunet init failed: %s", exc)
                self._yunet = None
        if recognizer_path.exists():
            try:
                if hasattr(cv2, "FaceRecognizerSF_create"):
                    self._sface = cv2.FaceRecognizerSF_create(str(recognizer_path), "")
                elif hasattr(cv2, "FaceRecognizerSF") and hasattr(cv2.FaceRecognizerSF, "create"):
                    self._sface = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
            except Exception as exc:
                logger.warning("sface init failed: %s", exc)
                self._sface = None

    def has_profile(self) -> bool:
        return self._owner_embedding is not None and bool(self._owner_profile)

    def get_status(self) -> Dict[str, object]:
        with self._lock:
            state = "ready" if self.has_profile() else "unenrolled"
            if bool(self._enrollment.get("active")):
                state = "enrolling"
            return {
                "identity_state": state,
                "owner_label": str(self._owner_profile.get("owner_label") or "owner"),
                "embedding_version": str(self._owner_profile.get("embedding_version") or ""),
                "embedding_backend": str(self._owner_profile.get("embedding_backend") or self._embedding_backend),
                "owner_recognized": self._last_recognition_label == "owner",
                "owner_confidence": round(float(self._last_recognition_confidence), 4),
                "recognition_label": self._last_recognition_label,
                "last_recognition_ts_ms": int(self._last_recognition_ts_ms or 0),
                "enrollment_active": bool(self._enrollment.get("active")),
                "enrollment_samples": int(len(self._enrollment.get("samples") or [])),
                "enrollment_target": int(self._config.enrollment_target_samples),
                "pending_sync": bool(self._pending_sync),
            }

    def get_pending_sync(self) -> Optional[Dict[str, object]]:
        with self._lock:
            if not self._pending_sync:
                return None
            return dict(self._pending_sync)

    def mark_sync_complete(self, embedding_version: str) -> None:
        with self._lock:
            if str(self._pending_sync.get("embedding_version") or "") != str(embedding_version or ""):
                return
            self._pending_sync = {}
            try:
                if self._pending_sync_path.exists():
                    self._pending_sync_path.unlink()
            except Exception:
                pass

    def start_enrollment(self, owner_label: str = "owner", claim_token: str = "") -> Dict[str, object]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._enrollment = {
                "active": True,
                "owner_label": str(owner_label or "owner").strip() or "owner",
                "claim_token": str(claim_token or "").strip(),
                "samples": [],
                "started_at_ms": now_ms,
                "last_sample_ms": 0,
                "last_bbox": None,
            }
            self._queue_event(
                "OwnerEnrollmentState",
                {
                    "state": "started",
                    "owner_label": self._enrollment["owner_label"],
                    "sample_count": 0,
                    "target_samples": int(self._config.enrollment_target_samples),
                },
            )
            return self.get_status()

    def reset_owner(self) -> Dict[str, object]:
        with self._lock:
            self._owner_embedding = None
            self._owner_profile = {}
            self._pending_sync = {}
            self._embedding_backend = "face-hist-v1"
            self._last_tracking_bbox = None
            self._last_recognition_label = "no_face"
            self._last_recognition_confidence = 0.0
            self._last_recognition_ts_ms = 0
            self._enrollment = {
                "active": False,
                "owner_label": "owner",
                "claim_token": "",
                "samples": [],
                "started_at_ms": 0,
                "last_sample_ms": 0,
                "last_bbox": None,
            }
            for path in (self._profile_path, self._embedding_path, self._pending_sync_path):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            self._queue_event("OwnerEnrollmentState", {"state": "reset"})
            return self.get_status()

    def pop_events(self) -> List[Dict[str, object]]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def process_frame(self, frame_bgr, timestamp_ms: int) -> Dict[str, object]:
        if not self.enabled or cv2 is None or np is None:
            return {"tracking_bbox": None, **self.get_status()}
        run_detect = bool(self._enrollment.get("active"))
        with self._lock:
            run_detect = run_detect or (timestamp_ms - self._last_process_ms >= int(self._config.recognition_interval_ms))
            last_bbox = self._last_tracking_bbox
        if not run_detect and last_bbox is not None:
            return {"tracking_bbox": last_bbox, **self.get_status()}

        faces = self._detect_faces(frame_bgr)
        with self._lock:
            self._last_process_ms = timestamp_ms
            if not faces:
                self._last_tracking_bbox = None
                self._update_recognition_state("no_face", 0.0, timestamp_ms)
                return {"tracking_bbox": None, **self.get_status()}

            target_face = max(faces, key=lambda item: int(item["bbox"][2]) * int(item["bbox"][3]))
            owner_confidence = 0.0
            owner_found = False
            if self._owner_embedding is not None:
                scored: List[Tuple[float, Dict[str, object]]] = []
                for face in faces:
                    embedding = self._extract_embedding(frame_bgr, face)
                    if embedding is None:
                        continue
                    similarity = self._cosine_similarity(self._owner_embedding, embedding)
                    scored.append((similarity, face))
                if scored:
                    best_score, best_face = max(scored, key=lambda item: item[0])
                    owner_confidence = float(best_score)
                    if best_score >= float(self._config.similarity_threshold):
                        owner_found = True
                        target_face = best_face

            self._last_tracking_bbox = tuple(target_face["bbox"])
            if bool(self._enrollment.get("active")):
                self._capture_enrollment_sample(frame_bgr, target_face, timestamp_ms)

            label = "owner" if owner_found else "unknown"
            self._update_recognition_state(label, owner_confidence if owner_found else 0.0, timestamp_ms)
            return {"tracking_bbox": tuple(target_face["bbox"]), **self.get_status()}

    def _capture_enrollment_sample(self, frame_bgr, face: Dict[str, object], timestamp_ms: int) -> None:
        last_sample_ms = int(self._enrollment.get("last_sample_ms") or 0)
        if timestamp_ms - last_sample_ms < int(self._config.enrollment_sample_interval_ms):
            return
        bbox = tuple(int(v) for v in (face.get("bbox") or (0, 0, 0, 0)))
        quality = self._face_quality(frame_bgr, bbox)
        if quality["area_ratio"] < 0.045 or quality["blur_score"] < 40.0:
            return
        if not self._is_bbox_stable(bbox):
            return
        embedding = self._extract_embedding(frame_bgr, face)
        if embedding is None:
            return
        samples = self._enrollment.get("samples")
        if not isinstance(samples, list):
            samples = []
            self._enrollment["samples"] = samples
        if samples and self._cosine_similarity(samples[-1], embedding) >= 0.995:
            self._enrollment["last_bbox"] = bbox
            return
        samples.append(embedding)
        self._enrollment["last_sample_ms"] = timestamp_ms
        self._enrollment["last_bbox"] = bbox
        sample_count = len(samples)
        self._queue_event(
            "OwnerEnrollmentState",
            {
                "state": "capturing",
                "owner_label": self._enrollment.get("owner_label"),
                "sample_count": sample_count,
                "target_samples": int(self._config.enrollment_target_samples),
                "blur_score": round(float(quality["blur_score"]), 2),
                "face_area_ratio": round(float(quality["area_ratio"]), 4),
            },
        )
        target = int(self._config.enrollment_target_samples)
        maximum = int(self._config.enrollment_max_samples)
        minimum = int(self._config.enrollment_min_samples)
        if sample_count < minimum:
            return
        if sample_count < target and sample_count < maximum:
            return
        self._finalize_enrollment(timestamp_ms)

    def _finalize_enrollment(self, timestamp_ms: int) -> None:
        samples = self._enrollment.get("samples")
        if not isinstance(samples, list) or not samples:
            return
        matrix = np.vstack(samples)
        embedding = matrix.mean(axis=0)
        norm = float(np.linalg.norm(embedding))
        if norm > 1e-6:
            embedding = embedding / norm
        version = str(timestamp_ms)
        owner_label = str(self._enrollment.get("owner_label") or "owner")
        sample_count = len(samples)
        profile = {
            "owner_label": owner_label,
            "embedding_version": version,
            "enrolled_at_ms": int(timestamp_ms),
            "sample_count": sample_count,
            "embedding_backend": self._embedding_backend,
            "similarity_threshold": float(self._config.similarity_threshold),
        }
        self._owner_embedding = embedding
        self._owner_profile = profile
        self._save_profile()
        claim_token = str(self._enrollment.get("claim_token") or "").strip()
        if claim_token:
            self._pending_sync = {
                "claim_token": claim_token,
                "owner_label": owner_label,
                "embedding_version": version,
                "sample_count": sample_count,
                "similarity_threshold": float(self._config.similarity_threshold),
                "enrolled_at_ms": int(timestamp_ms),
                "embedding_backend": self._embedding_backend,
            }
            self._save_json(self._pending_sync_path, self._pending_sync)
        self._enrollment = {
            "active": False,
            "owner_label": owner_label,
            "claim_token": "",
            "samples": [],
            "started_at_ms": 0,
            "last_sample_ms": 0,
            "last_bbox": None,
        }
        self._queue_event(
            "OwnerEnrollmentState",
            {
                "state": "completed",
                "owner_label": owner_label,
                "sample_count": sample_count,
                "embedding_version": version,
            },
        )

    def _load_state(self) -> None:
        profile = self._load_json(self._profile_path)
        if profile and np is not None and self._embedding_path.exists():
            try:
                self._owner_embedding = np.load(str(self._embedding_path))
                self._owner_profile = profile
                self._embedding_backend = str(profile.get("embedding_backend") or self._embedding_backend)
            except Exception as exc:
                logger.warning("identity profile load failed: %s", exc)
                self._owner_embedding = None
                self._owner_profile = {}
        pending = self._load_json(self._pending_sync_path)
        if pending:
            self._pending_sync = pending

    def _save_profile(self) -> None:
        if self._owner_embedding is None:
            return
        self._save_json(self._profile_path, self._owner_profile)
        np.save(str(self._embedding_path), self._owner_embedding)

    def _detect_faces(self, frame_bgr) -> List[Dict[str, object]]:
        if frame_bgr is None or cv2 is None:
            return []
        if self._yunet is not None:
            detected = self._detect_faces_yunet(frame_bgr)
            if detected:
                return detected
        return self._detect_faces_haar(frame_bgr)

    def _detect_faces_yunet(self, frame_bgr) -> List[Dict[str, object]]:
        if self._yunet is None:
            return []
        try:
            height, width = frame_bgr.shape[:2]
            self._yunet.setInputSize((int(width), int(height)))
            _ok, faces = self._yunet.detect(frame_bgr)
        except Exception:
            return []
        results: List[Dict[str, object]] = []
        if faces is None:
            return results
        for row in faces:
            try:
                values = [float(v) for v in row.tolist()]
                x, y, w, h = [int(round(v)) for v in values[:4]]
                if w <= 0 or h <= 0:
                    continue
                landmarks = tuple(float(v) for v in values[4:14]) if len(values) >= 14 else None
                score = float(values[14]) if len(values) >= 15 else 1.0
                results.append({"bbox": (x, y, w, h), "score": score, "landmarks": landmarks, "backend": "yunet"})
            except Exception:
                continue
        return results

    def _detect_faces_haar(self, frame_bgr) -> List[Dict[str, object]]:
        if self._cascade is None or frame_bgr is None:
            return []
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40),
            )
        except Exception:
            return []
        results: List[Dict[str, object]] = []
        for item in faces or []:
            x, y, w, h = [int(v) for v in item]
            if w > 0 and h > 0:
                results.append({"bbox": (x, y, w, h), "score": 1.0, "landmarks": None, "backend": "haar"})
        return results

    def _extract_embedding(self, frame_bgr, face: Dict[str, object]):
        if frame_bgr is None or np is None or cv2 is None:
            return None
        bbox = tuple(int(v) for v in (face.get("bbox") or (0, 0, 0, 0)))
        x, y, w, h = bbox
        crop = frame_bgr[max(0, y) : max(0, y) + max(1, h), max(0, x) : max(0, x) + max(1, w)]
        if crop is None or crop.size == 0:
            return None
        recognizer_embedding = self._extract_sface_embedding(frame_bgr, face)
        if recognizer_embedding is not None:
            self._embedding_backend = "opencv-sface-v1"
            return recognizer_embedding
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            gray_small = cv2.resize(gray, (16, 16)).astype("float32").reshape(-1) / 255.0
            hist = cv2.calcHist([gray], [0], None, [32], [0, 256]).astype("float32").reshape(-1)
            hist_sum = float(hist.sum())
            if hist_sum > 1e-6:
                hist /= hist_sum
            embedding = np.concatenate([gray_small, hist], axis=0)
            norm = float(np.linalg.norm(embedding))
            if norm > 1e-6:
                embedding = embedding / norm
            self._embedding_backend = "face-hist-v1"
            return embedding
        except Exception:
            return None

    def _extract_sface_embedding(self, frame_bgr, face: Dict[str, object]):
        if self._sface is None or np is None or cv2 is None:
            return None
        landmarks = face.get("landmarks")
        bbox = tuple(int(v) for v in (face.get("bbox") or (0, 0, 0, 0)))
        if not landmarks or len(landmarks) < 10:
            return None
        try:
            detection_row = np.asarray([*bbox, *[float(v) for v in landmarks[:10]], float(face.get("score") or 1.0)], dtype="float32")
            aligned = self._sface.alignCrop(frame_bgr, detection_row)
            feature = self._sface.feature(aligned)
            embedding = np.asarray(feature, dtype="float32").reshape(-1)
            norm = float(np.linalg.norm(embedding))
            if norm > 1e-6:
                embedding = embedding / norm
            return embedding
        except Exception:
            return None

    def _face_quality(self, frame_bgr, bbox: Tuple[int, int, int, int]) -> Dict[str, float]:
        if frame_bgr is None or cv2 is None or np is None:
            return {"blur_score": 0.0, "area_ratio": 0.0}
        x, y, w, h = bbox
        crop = frame_bgr[max(0, y) : max(0, y) + max(1, h), max(0, x) : max(0, x) + max(1, w)]
        if crop is None or crop.size == 0:
            return {"blur_score": 0.0, "area_ratio": 0.0}
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        except Exception:
            blur_score = 0.0
        frame_area = float(max(1, frame_bgr.shape[0] * frame_bgr.shape[1]))
        area_ratio = float((max(1, w) * max(1, h)) / frame_area)
        return {"blur_score": blur_score, "area_ratio": area_ratio}

    def _is_bbox_stable(self, bbox: Tuple[int, int, int, int]) -> bool:
        previous = self._enrollment.get("last_bbox")
        if not previous or not isinstance(previous, tuple) or len(previous) != 4:
            return True
        return self._bbox_iou(previous, bbox) >= 0.42

    def _bbox_iou(self, first: Tuple[int, int, int, int], second: Tuple[int, int, int, int]) -> float:
        ax, ay, aw, ah = first
        bx, by, bw, bh = second
        inter_x1 = max(ax, bx)
        inter_y1 = max(ay, by)
        inter_x2 = min(ax + aw, bx + bw)
        inter_y2 = min(ay + ah, by + bh)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        union = max(1, aw * ah + bw * bh - inter)
        return float(inter / union)

    def _cosine_similarity(self, base, sample) -> float:
        if base is None or sample is None or np is None:
            return 0.0
        try:
            return float(np.dot(base, sample))
        except Exception:
            return 0.0

    def _update_recognition_state(self, label: str, confidence: float, timestamp_ms: int) -> None:
        label = str(label or "no_face")
        confidence = float(confidence or 0.0)
        changed = (
            label != self._last_recognition_label
            or abs(confidence - self._last_recognition_confidence) >= 0.08
        )
        self._last_recognition_label = label
        self._last_recognition_confidence = confidence
        self._last_recognition_ts_ms = int(timestamp_ms)
        if changed:
            self._queue_event(
                "OwnerRecognitionUpdate",
                {
                    "state": label,
                    "owner_recognized": label == "owner",
                    "confidence": round(confidence, 4),
                    "owner_label": str(self._owner_profile.get("owner_label") or "owner"),
                    "embedding_version": str(self._owner_profile.get("embedding_version") or ""),
                },
            )

    def _queue_event(self, event_type: str, payload: Dict[str, object]) -> None:
        self._events.append({"type": event_type, "payload": dict(payload)})

    def _load_json(self, path: Path) -> Dict[str, object]:
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_json(self, path: Path, payload: Dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
