(function () {
  const form = document.getElementById("guest-upload-form");
  if (!form) {
    return;
  }

  const fileInput = form.querySelector("input[type='file']");
  const selectedFileName = document.getElementById("selected-file-name");
  const clientDurationInput = document.getElementById("client-duration-seconds");
  const capturePreview = document.getElementById("capture-preview");
  const previewImage = document.getElementById("capture-preview-image");
  const previewVideo = document.getElementById("capture-preview-video");
  const previewDetails = document.getElementById("capture-preview-details");
  const replaceMediaButton = document.getElementById("replace-media-button");
  const retakeCameraButton = document.getElementById("retake-camera-button");
  const cameraStudio = document.getElementById("camera-studio");
  const startCameraButton = document.getElementById("start-camera-button");
  const cameraPanel = document.getElementById("camera-panel");
  const liveVideo = document.getElementById("camera-live-video");
  const cameraStatus = document.getElementById("camera-status");
  const cameraFeedback = document.getElementById("camera-feedback");
  const recordingBadge = document.getElementById("camera-recording-badge");
  const recordingTimer = document.getElementById("camera-recording-timer");
  const backCameraButton = document.getElementById("back-camera-button");
  const selfieCameraButton = document.getElementById("selfie-camera-button");
  const photoModeButton = document.getElementById("photo-mode-button");
  const videoModeButton = document.getElementById("video-mode-button");
  const capturePhotoButton = document.getElementById("capture-photo-button");
  const recordVideoButton = document.getElementById("record-video-button");
  const stopVideoButton = document.getElementById("stop-video-button");
  const closeCameraButton = document.getElementById("close-camera-button");
  const filterButtons = document.querySelectorAll("[data-camera-filter]");
  const progress = form.querySelector(".upload-progress");
  const progressBar = form.querySelector(".upload-progress__bar span");
  const progressText = form.querySelector(".upload-progress p");
  const submitButton = form.querySelector("button[type='submit']");
  const initialSubmitLabel = submitButton ? submitButton.textContent : "";
  let previewUrl = "";
  let cameraStream = null;
  let facingMode = "environment";
  let activeFilter = "none";
  let recorder = null;
  let recordedChunks = [];
  let recordingTimeout = null;
  let recordingStartedAt = 0;
  let recordingInterval = null;
  let pendingCapturedDuration = null;
  let cameraMode = "photo";
  let isSwitchingCamera = false;
  const maxRecordingSeconds = 10;

  const cameraFilters = {
    none: "none",
    soft: "contrast(1.04) saturate(1.14) brightness(1.06)",
    warm: "sepia(0.18) saturate(1.25) contrast(1.04)",
    mono: "grayscale(1) contrast(1.12)",
  };

  function resetPreviewUrl() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }
  }

  function clearPreview() {
    resetPreviewUrl();
    if (capturePreview) {
      capturePreview.hidden = true;
    }
    if (previewImage) {
      previewImage.removeAttribute("src");
      previewImage.hidden = true;
    }
    if (previewVideo) {
      previewVideo.removeAttribute("src");
      previewVideo.hidden = true;
      previewVideo.load();
    }
    if (previewDetails) {
      previewDetails.textContent = "Verifiez l'apercu, choisissez le moment, puis envoyez.";
    }
  }

  function setClientDuration(durationSeconds) {
    if (!clientDurationInput) {
      return;
    }
    if (durationSeconds && Number.isFinite(durationSeconds)) {
      clientDurationInput.value = Math.min(durationSeconds, maxRecordingSeconds).toFixed(2);
      return;
    }
    clientDurationInput.value = "";
  }

  function setCameraOpen(isOpen) {
    document.body.classList.toggle("camera-open", isOpen);
    if (cameraStudio) {
      cameraStudio.classList.toggle("camera-studio--active", isOpen);
    }
  }

  function updateCameraUi() {
    if (liveVideo) {
      liveVideo.classList.toggle("is-selfie", facingMode === "user");
    }
    if (backCameraButton) {
      backCameraButton.classList.toggle("is-active", facingMode === "environment");
      backCameraButton.disabled = isSwitchingCamera || facingMode === "environment";
    }
    if (selfieCameraButton) {
      selfieCameraButton.classList.toggle("is-active", facingMode === "user");
      selfieCameraButton.disabled = isSwitchingCamera || facingMode === "user";
    }
    if (photoModeButton) {
      photoModeButton.classList.toggle("is-active", cameraMode === "photo");
    }
    if (videoModeButton) {
      videoModeButton.classList.toggle("is-active", cameraMode === "video");
    }
    if (capturePhotoButton) {
      capturePhotoButton.hidden = cameraMode !== "photo" || (recorder && recorder.state === "recording");
    }
    if (recordVideoButton) {
      recordVideoButton.hidden = cameraMode !== "video" || (recorder && recorder.state === "recording");
    }
    if (stopVideoButton) {
      stopVideoButton.hidden = !(recorder && recorder.state === "recording");
    }
  }

  function showCameraFeedback(message, tone) {
    if (!cameraFeedback) {
      return;
    }
    cameraFeedback.textContent = message;
    cameraFeedback.hidden = false;
    cameraFeedback.classList.toggle("camera-feedback--success", tone === "success");
    cameraFeedback.classList.toggle("camera-feedback--recording", tone === "recording");
    window.setTimeout(function () {
      if (cameraFeedback.textContent === message) {
        cameraFeedback.hidden = true;
      }
    }, tone === "recording" ? 1200 : 1800);
  }

  function setRecordingState(isRecording) {
    document.body.classList.toggle("camera-is-recording", isRecording);
    if (recordingBadge) {
      recordingBadge.hidden = !isRecording;
    }
    if (!isRecording && recordingTimer) {
      recordingTimer.textContent = "0,0 s";
    }
    updateCameraUi();
  }

  function updateRecordingTimer() {
    if (!recordingTimer || !recordingStartedAt) {
      return;
    }
    const elapsed = Math.min((Date.now() - recordingStartedAt) / 1000, maxRecordingSeconds);
    recordingTimer.textContent = formatDuration(elapsed);
    setCameraStatus("Video en cours - stop pour terminer");
  }

  function formatFileSize(bytes) {
    if (!bytes) {
      return "";
    }
    if (bytes < 1024 * 1024) {
      return Math.max(1, Math.round(bytes / 1024)) + " Ko";
    }
    return (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") + " Mo";
  }

  function formatDuration(durationSeconds) {
    if (!durationSeconds || !Number.isFinite(durationSeconds)) {
      return "";
    }
    return durationSeconds.toFixed(durationSeconds >= 10 ? 0 : 1).replace(".", ",") + " s";
  }

  function setCameraStatus(message) {
    if (cameraStatus) {
      cameraStatus.textContent = message;
    }
  }

  function cameraConstraints(exactFacingMode) {
    return {
      audio: true,
      video: {
        facingMode: exactFacingMode ? { exact: facingMode } : { ideal: facingMode },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
    };
  }

  async function requestCameraStream() {
    try {
      return await navigator.mediaDevices.getUserMedia(cameraConstraints(true));
    } catch {
      return navigator.mediaDevices.getUserMedia(cameraConstraints(false));
    }
  }

  function stopCamera(options) {
    const hidePanel = !options || options.hidePanel !== false;
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
    }
    if (recordingInterval) {
      clearInterval(recordingInterval);
      recordingInterval = null;
    }
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    if (cameraStream) {
      cameraStream.getTracks().forEach(function (track) {
        track.stop();
      });
      cameraStream = null;
    }
    if (liveVideo) {
      liveVideo.srcObject = null;
    }
    if (cameraPanel && hidePanel) {
      cameraPanel.hidden = true;
    }
    if (hidePanel) {
      setCameraOpen(false);
    }
    setRecordingState(false);
    updateCameraUi();
  }

  async function startCamera(options) {
    const preservePanel = options && options.preservePanel;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !liveVideo) {
      if (cameraStudio) {
        cameraStudio.classList.add("camera-studio--unsupported");
      }
      setCameraStatus("Camera integree indisponible. Utilisez l'appareil natif.");
      return;
    }

    stopCamera({ hidePanel: !preservePanel });
    if (cameraPanel) {
      cameraPanel.hidden = false;
    }
    setCameraOpen(true);
    updateCameraUi();
    setCameraStatus(preservePanel ? "Changement de camera..." : "Ouverture de la camera...");
    try {
      cameraStream = await requestCameraStream();
      liveVideo.srcObject = cameraStream;
      liveVideo.style.filter = cameraFilters[activeFilter] || "none";
      setCameraStatus(facingMode === "user" ? "Selfie actif" : "Camera arriere active");
      updateCameraUi();
    } catch {
      setCameraOpen(false);
      if (cameraPanel) {
        cameraPanel.hidden = true;
      }
      setCameraStatus("Autorisez la camera ou utilisez l'appareil natif.");
    }
  }

  function timestamp() {
    return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  }

  function setCapturedFile(blob, filename, durationSeconds) {
    if (!fileInput || !window.DataTransfer || !window.File) {
      setCameraStatus("Capture prete. Votre navigateur demande l'appareil natif.");
      return;
    }

    const file = new File([blob], filename, { type: blob.type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    pendingCapturedDuration = durationSeconds || null;
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    setCameraStatus("Souvenir pret a envoyer");
  }

  function showPreviewAfterCapture(message) {
    showCameraFeedback(message, "success");
    window.setTimeout(function () {
      stopCamera();
      if (capturePreview) {
        capturePreview.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 450);
  }

  function capturePhoto() {
    if (!liveVideo || !cameraStream) {
      return;
    }

    setCameraStatus("Capture de la photo...");
    showCameraFeedback("Photo prise", "success");
    const canvas = document.createElement("canvas");
    canvas.width = liveVideo.videoWidth || 1280;
    canvas.height = liveVideo.videoHeight || 720;
    const context = canvas.getContext("2d");
    context.filter = cameraFilters[activeFilter] || "none";
    if (facingMode === "user") {
      context.translate(canvas.width, 0);
      context.scale(-1, 1);
    }
    context.drawImage(liveVideo, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      if (blob) {
        setCapturedFile(blob, "memora-photo-" + timestamp() + ".jpg");
        showPreviewAfterCapture("Photo prise");
      }
    }, "image/jpeg", 0.92);
  }

  function supportedVideoMimeType() {
    if (!window.MediaRecorder) {
      return "";
    }
    const candidates = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"];
    return candidates.find(function (candidate) {
      return MediaRecorder.isTypeSupported(candidate);
    }) || "";
  }

  function startVideoRecording() {
    if (!cameraStream || !window.MediaRecorder) {
      setCameraStatus("Video integree indisponible. Utilisez l'appareil natif.");
      return;
    }

    const mimeType = supportedVideoMimeType();
    recordedChunks = [];
    recorder = new MediaRecorder(cameraStream, mimeType ? { mimeType: mimeType } : undefined);
    recorder.addEventListener("dataavailable", function (event) {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    });
    recorder.addEventListener("stop", function () {
      if (recordingTimeout) {
        clearTimeout(recordingTimeout);
        recordingTimeout = null;
      }
      if (recordingInterval) {
        clearInterval(recordingInterval);
        recordingInterval = null;
      }
      const recordedSeconds = recordingStartedAt ? (Date.now() - recordingStartedAt) / 1000 : maxRecordingSeconds;
      const recordedType = recorder.mimeType || mimeType || "video/webm";
      const extension = recordedType.indexOf("mp4") >= 0 ? "mp4" : "webm";
      const blob = new Blob(recordedChunks, { type: recordedType });
      setCapturedFile(blob, "memora-video-" + timestamp() + "." + extension, recordedSeconds);
      recordedChunks = [];
      recordingStartedAt = 0;
      setRecordingState(false);
      showPreviewAfterCapture("Video prete");
    });
    recorder.start();
    recordingStartedAt = Date.now();
    updateRecordingTimer();
    recordingInterval = setInterval(updateRecordingTimer, 200);
    recordingTimeout = setTimeout(stopVideoRecording, maxRecordingSeconds * 1000);
    setRecordingState(true);
    showCameraFeedback("Enregistrement", "recording");
    setCameraStatus("Video en cours - stop pour terminer");
  }

  function stopVideoRecording() {
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
    }
    if (recorder && recorder.state !== "inactive") {
      setCameraStatus("Preparation de la video...");
      recorder.stop();
    }
    setRecordingState(false);
  }

  if (cameraStudio && (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)) {
    cameraStudio.classList.add("camera-studio--unsupported");
  }
  updateCameraUi();

  if (startCameraButton) {
    startCameraButton.addEventListener("click", startCamera);
  }

  function selectFacingMode(nextFacingMode) {
    if (facingMode === nextFacingMode || isSwitchingCamera) {
      return;
    }
    facingMode = nextFacingMode;
    isSwitchingCamera = true;
    updateCameraUi();
    startCamera({ preservePanel: true }).finally(function () {
      isSwitchingCamera = false;
      updateCameraUi();
    });
  }

  if (backCameraButton) {
    backCameraButton.addEventListener("click", function () {
      selectFacingMode("environment");
    });
  }

  if (selfieCameraButton) {
    selfieCameraButton.addEventListener("click", function () {
      selectFacingMode("user");
    });
  }

  if (photoModeButton) {
    photoModeButton.addEventListener("click", function () {
      cameraMode = "photo";
      setCameraStatus(facingMode === "user" ? "Selfie actif - appuyez sur Photo" : "Camera arriere active - appuyez sur Photo");
      updateCameraUi();
    });
  }

  if (videoModeButton) {
    videoModeButton.addEventListener("click", function () {
      cameraMode = "video";
      setCameraStatus("Mode video - appuyez sur Video");
      updateCameraUi();
    });
  }

  if (capturePhotoButton) {
    capturePhotoButton.addEventListener("click", capturePhoto);
  }

  if (recordVideoButton) {
    recordVideoButton.addEventListener("click", startVideoRecording);
  }

  if (stopVideoButton) {
    stopVideoButton.addEventListener("click", stopVideoRecording);
  }

  if (closeCameraButton) {
    closeCameraButton.addEventListener("click", stopCamera);
  }

  filterButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      activeFilter = button.dataset.cameraFilter || "none";
      filterButtons.forEach(function (item) {
        item.classList.toggle("is-active", item === button);
      });
      if (liveVideo) {
        liveVideo.style.filter = cameraFilters[activeFilter] || "none";
      }
    });
  });

  if (fileInput && selectedFileName) {
    fileInput.addEventListener("change", function () {
      const file = fileInput.files && fileInput.files[0];
      selectedFileName.textContent = file ? "Souvenir pret : " + file.name : "JPG, PNG, WEBP, MP4, MOV ou WEBM.";

      clearPreview();
      const capturedDuration = pendingCapturedDuration;
      pendingCapturedDuration = null;
      setClientDuration(capturedDuration);
      if (!file || !capturePreview || !window.URL || !URL.createObjectURL) {
        return;
      }

      previewUrl = URL.createObjectURL(file);
      capturePreview.hidden = false;
      if (previewDetails) {
        const sizeLabel = formatFileSize(file.size);
        previewDetails.textContent = sizeLabel ? "Apercu pret - " + sizeLabel + "." : "Apercu pret.";
      }

      if (file.type.indexOf("image/") === 0 && previewImage) {
        previewImage.src = previewUrl;
        previewImage.hidden = false;
        if (previewDetails) {
          const sizeLabel = formatFileSize(file.size);
          previewDetails.textContent = sizeLabel ? "Photo prete - " + sizeLabel + "." : "Photo prete.";
        }
        return;
      }

      if (file.type.indexOf("video/") === 0 && previewVideo) {
        previewVideo.src = previewUrl;
        previewVideo.hidden = false;
        if (previewDetails) {
          const sizeLabel = formatFileSize(file.size);
          previewDetails.textContent = sizeLabel ? "Video prete - " + sizeLabel + "." : "Video prete.";
        }
        previewVideo.addEventListener("loadedmetadata", function handleMetadata() {
          const duration = previewVideo.duration;
          if (duration && Number.isFinite(duration)) {
            setClientDuration(duration);
            if (previewDetails) {
              const sizeLabel = formatFileSize(file.size);
              const parts = ["Video prete", formatDuration(duration), sizeLabel].filter(Boolean);
              previewDetails.textContent = parts.join(" - ") + ".";
            }
          }
        }, { once: true });
        previewVideo.load();
      }
    });
  }

  if (replaceMediaButton && fileInput) {
    replaceMediaButton.addEventListener("click", function () {
      fileInput.click();
    });
  }

  if (retakeCameraButton) {
    retakeCameraButton.addEventListener("click", startCamera);
  }

  form.addEventListener("submit", function (event) {
    if (!window.XMLHttpRequest || !window.FormData) {
      return;
    }

    event.preventDefault();

    if (progress) {
      progress.hidden = false;
    }
    if (progressBar) {
      progressBar.style.width = "0%";
    }
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Envoi...";
    }
    if (progressText) {
      progressText.textContent = "Preparation de l'envoi...";
    }

    const request = new XMLHttpRequest();
    request.open(form.method || "POST", form.action);
    request.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    request.upload.addEventListener("progress", function (progressEvent) {
      if (!progressEvent.lengthComputable || !progressBar) {
        return;
      }
      const percent = Math.max(8, Math.min(96, Math.round((progressEvent.loaded / progressEvent.total) * 100)));
      progressBar.style.width = percent + "%";
      if (progressText) {
        progressText.textContent = "Envoi en cours... " + percent + "%";
      }
    });

    request.addEventListener("load", function () {
      if (progressBar) {
        progressBar.style.width = "100%";
      }

      const responseUrl = request.responseURL || form.action;
      const currentAction = new URL(form.action, window.location.href).href;

      if (request.status >= 200 && request.status < 300 && responseUrl !== currentAction) {
        window.location.assign(responseUrl);
        return;
      }

      document.open();
      document.write(request.responseText);
      document.close();
    });

    request.addEventListener("error", function () {
      if (progressText) {
        progressText.textContent = "L'envoi a echoue. Reessayez.";
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
    });

    request.send(new FormData(form));
  });
})();
