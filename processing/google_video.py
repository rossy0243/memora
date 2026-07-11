from django.conf import settings


GOOGLE_PROVIDER = "google_video_intelligence_v1"


def analyze_video_with_google(source_path):
    try:
        from google.cloud import videointelligence_v1 as videointelligence
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-videointelligence n'est pas installe. "
            "Installe les dependances avec pip install -r requirements.txt."
        ) from exc

    client = videointelligence.VideoIntelligenceServiceClient()
    features = [
        videointelligence.Feature.LABEL_DETECTION,
        videointelligence.Feature.SHOT_CHANGE_DETECTION,
        videointelligence.Feature.EXPLICIT_CONTENT_DETECTION,
        videointelligence.Feature.FACE_DETECTION,
        videointelligence.Feature.SPEECH_TRANSCRIPTION,
    ]

    model_name = "builtin/latest" if settings.MEMORA_GOOGLE_VIDEO_INTELLIGENCE_USE_LATEST_MODEL else "builtin/stable"
    video_context = videointelligence.VideoContext(
        label_detection_config=videointelligence.LabelDetectionConfig(model=model_name),
        shot_change_detection_config=videointelligence.ShotChangeDetectionConfig(model=model_name),
        explicit_content_detection_config=videointelligence.ExplicitContentDetectionConfig(model=model_name),
        face_detection_config=videointelligence.FaceDetectionConfig(
            model=model_name,
            include_bounding_boxes=True,
            include_attributes=True,
        ),
        speech_transcription_config=videointelligence.SpeechTranscriptionConfig(
            language_code=settings.MEMORA_GOOGLE_VIDEO_INTELLIGENCE_LANGUAGE,
            enable_automatic_punctuation=True,
            filter_profanity=True,
        ),
    )

    with open(source_path, "rb") as video_file:
        operation = client.annotate_video(
            request={
                "features": features,
                "input_content": video_file.read(),
                "video_context": video_context,
            }
        )

    result = operation.result(timeout=settings.MEMORA_GOOGLE_VIDEO_INTELLIGENCE_TIMEOUT_SECONDS)
    if not result.annotation_results:
        return _empty_result()

    annotations = result.annotation_results[0]
    return {
        "provider": GOOGLE_PROVIDER,
        "labels": _extract_labels(annotations),
        "shot_count": len(getattr(annotations, "shot_annotations", []) or []),
        "explicit_content": _extract_explicit_content(annotations),
        "face_track_count": len(getattr(annotations, "face_detection_annotations", []) or []),
        "speech_segments": _extract_speech_segments(annotations),
    }


def _empty_result():
    return {
        "provider": GOOGLE_PROVIDER,
        "labels": [],
        "shot_count": 0,
        "explicit_content": {"max_likelihood": 0, "max_likelihood_name": "UNKNOWN"},
        "face_track_count": 0,
        "speech_segments": [],
    }


def _extract_labels(annotations):
    labels = []
    for annotation in list(getattr(annotations, "segment_label_annotations", []) or [])[:24]:
        description = getattr(annotation.entity, "description", "")
        confidence = 0
        if annotation.segments:
            confidence = max(segment.confidence for segment in annotation.segments)
        if description:
            labels.append({"description": description, "confidence": round(float(confidence), 4)})
    return labels


def _extract_explicit_content(annotations):
    explicit_annotation = getattr(annotations, "explicit_annotation", None)
    frames = list(getattr(explicit_annotation, "frames", []) or [])
    if not frames:
        return {"max_likelihood": 0, "max_likelihood_name": "UNKNOWN"}

    max_likelihood = max(int(frame.pornography_likelihood) for frame in frames)
    return {
        "max_likelihood": max_likelihood,
        "max_likelihood_name": _likelihood_name(max_likelihood),
    }


def _extract_speech_segments(annotations):
    segments = []
    for transcription in list(getattr(annotations, "speech_transcriptions", []) or [])[:8]:
        if not transcription.alternatives:
            continue
        alternative = transcription.alternatives[0]
        words = list(getattr(alternative, "words", []) or [])
        start = _duration_to_seconds(words[0].start_time) if words else None
        end = _duration_to_seconds(words[-1].end_time) if words else None
        segments.append(
            {
                "transcript": alternative.transcript[:280],
                "confidence": round(float(alternative.confidence or 0), 4),
                "start": start,
                "end": end,
                "word_count": len(words),
            }
        )
    return segments


def _duration_to_seconds(value):
    seconds = getattr(value, "seconds", 0) or 0
    nanos = getattr(value, "nanos", 0) or 0
    return round(seconds + nanos / 1_000_000_000, 3)


def _likelihood_name(value):
    names = {
        0: "UNKNOWN",
        1: "VERY_UNLIKELY",
        2: "UNLIKELY",
        3: "POSSIBLE",
        4: "LIKELY",
        5: "VERY_LIKELY",
    }
    return names.get(int(value), "UNKNOWN")
