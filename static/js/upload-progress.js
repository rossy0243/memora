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
  const useCaptureButton = document.getElementById("use-capture-button");
  const previewBackdrop = document.getElementById("capture-preview-backdrop");
  const cameraStudio = document.getElementById("camera-studio");
  const startCameraButton = document.getElementById("start-camera-button");
  const cameraPanel = document.getElementById("camera-panel");
  const cameraPermissionNote = document.getElementById("camera-permission-note");
  const liveVideo = document.getElementById("camera-live-video");
  const cameraStatus = document.getElementById("camera-status");
  const cameraFeedback = document.getElementById("camera-feedback");
  const recordingBadge = document.getElementById("camera-recording-badge");
  const recordingTimer = document.getElementById("camera-recording-timer");
  const lensToggleButton = document.getElementById("lens-toggle-button");
  const modeToggleButton = document.getElementById("mode-toggle-button");
  const cameraActionButton = document.getElementById("camera-action-button");
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
  let isStoppingRecording = false;
  const maxRecordingSeconds = 10;
  let slowUploadTimer = null;
  let verySlowUploadTimer = null;

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
    closeCaptureReview();
    if (capturePreview) {
      capturePreview.hidden = true;
    }
    if (previewBackdrop) {
      previewBackdrop.removeAttribute("src");
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
      previewDetails.textContent = "Vérifiez l'aperçu, choisissez le moment, puis envoyez.";
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
    const isRecording = recorder && recorder.state === "recording";
    if (liveVideo) {
      liveVideo.classList.toggle("is-selfie", facingMode === "user");
    }
    if (lensToggleButton) {
      lensToggleButton.textContent = facingMode === "user" ? "Arrière" : "Selfie";
      lensToggleButton.setAttribute("aria-label", facingMode === "user" ? "Passer en caméra arrière" : "Passer en selfie");
      lensToggleButton.disabled = isSwitchingCamera || isRecording;
      lensToggleButton.classList.toggle("is-active", facingMode === "environment");
      lensToggleButton.classList.toggle("is-selfie", facingMode === "user");
      lensToggleButton.classList.toggle("is-switching", isSwitchingCamera);
    }
    if (modeToggleButton) {
      modeToggleButton.textContent = cameraMode === "photo" ? "Vidéo" : "Photo";
      modeToggleButton.setAttribute("aria-label", cameraMode === "photo" ? "Passer en vidéo" : "Passer en photo");
      modeToggleButton.disabled = isRecording;
      modeToggleButton.classList.toggle("is-active", cameraMode === "photo");
      modeToggleButton.classList.toggle("is-video", cameraMode === "video");
    }
    if (cameraActionButton) {
      cameraActionButton.classList.toggle("camera-shutter--video", cameraMode === "video" && !isRecording);
      cameraActionButton.classList.toggle("camera-shutter--stop", isRecording);
      cameraActionButton.classList.toggle("camera-shutter--stopping", isStoppingRecording);
      cameraActionButton.disabled = isStoppingRecording;
      cameraActionButton.setAttribute(
        "aria-label",
        isStoppingRecording
          ? "Préparation de la vidéo"
          : isRecording
            ? "Stopper la vidéo"
            : cameraMode === "video"
              ? "Lancer la vidéo"
              : "Prendre la photo",
      );
      const label = cameraActionButton.querySelector("strong");
      if (label) {
        label.textContent = isStoppingRecording ? "..." : isRecording ? "Stop" : cameraMode === "video" ? "Vidéo" : "Photo";
      }
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
      recordingBadge.hidden = !isRecording || isStoppingRecording;
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
    setCameraStatus("Vidéo en cours - stop pour terminer");
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

  function setPermissionNote(message, tone) {
    if (!cameraPermissionNote) {
      return;
    }
    cameraPermissionNote.textContent = message;
    cameraPermissionNote.classList.toggle("is-warning", tone === "warning");
    cameraPermissionNote.classList.toggle("is-ok", tone === "ok");
  }

  function cameraErrorMessage(error) {
    if (!error) {
      return "La caméra n'a pas pu s'ouvrir. Essayez l'appareil natif.";
    }
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Autorisez la caméra et le micro pour capturer avec Memora.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "Aucune caméra disponible. Utilisez l'appareil natif.";
    }
    if (error.name === "NotReadableError" || error.name === "TrackStartError") {
      return "La caméra est déjà utilisée par une autre application.";
    }
    if (error.name === "OverconstrainedError" || error.name === "ConstraintNotSatisfiedError") {
      return "Cet objectif n'est pas disponible sur ce téléphone.";
    }
    return "La caméra n'a pas pu s'ouvrir. Essayez l'appareil natif.";
  }

  async function refreshCameraPermissionHint() {
    if (!navigator.permissions || !navigator.permissions.query) {
      return;
    }
    try {
      const permission = await navigator.permissions.query({ name: "camera" });
      if (permission.state === "granted") {
        setPermissionNote("Caméra autorisée. Vous pouvez capturer directement ici.", "ok");
      } else if (permission.state === "denied") {
        setPermissionNote("Caméra bloquée. Activez l'autorisation dans votre navigateur.", "warning");
      } else {
        setPermissionNote("Votre navigateur demandera l'autorisation caméra et micro.");
      }
      permission.onchange = refreshCameraPermissionHint;
    } catch {
      // Safari mobile ne supporte pas toujours l'API Permissions pour la camera.
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
      setCameraStatus("Caméra intégrée indisponible. Utilisez l'appareil natif.");
      return;
    }

    stopCamera({ hidePanel: !preservePanel });
    if (cameraPanel) {
      cameraPanel.hidden = false;
    }
    setCameraOpen(true);
    updateCameraUi();
    setCameraStatus(preservePanel ? "Changement de caméra..." : "Ouverture de la caméra...");
    try {
      cameraStream = await requestCameraStream();
      liveVideo.srcObject = cameraStream;
      liveVideo.style.filter = cameraFilters[activeFilter] || "none";
      setCameraStatus(facingMode === "user" ? "Selfie actif" : "Caméra arrière active");
      updateCameraUi();
    } catch (error) {
      setCameraOpen(false);
      if (cameraPanel) {
        cameraPanel.hidden = true;
      }
      const message = cameraErrorMessage(error);
      setPermissionNote(message, "warning");
      setCameraStatus(message);
    }
  }

  function timestamp() {
    return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  }

  function setCapturedFile(blob, filename, durationSeconds) {
    if (!fileInput || !window.DataTransfer || !window.File) {
      setCameraStatus("Capture prête. Votre navigateur demande l'appareil natif.");
      return;
    }

    const file = new File([blob], filename, { type: blob.type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    pendingCapturedDuration = durationSeconds || null;
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    setCameraStatus("Souvenir prêt à envoyer");
  }

  function openCaptureReview() {
    document.body.classList.add("capture-review-open");
  }

  function closeCaptureReview() {
    document.body.classList.remove("capture-review-open");
  }

  function showPreviewAfterCapture(message) {
    showCameraFeedback(message, "success");
    // On reste en plein ecran : l'image capturee remplace le flux au meme endroit,
    // comme un appareil photo natif. Pas d'attente, pas de sortie, pas de defilement.
    // stopCamera libere la camera et masque le panneau dans le meme tick que
    // l'ouverture de la revue : le navigateur ne peint jamais la page intermediaire.
    stopCamera();
    openCaptureReview();
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
      setCameraStatus("Vidéo intégrée indisponible. Utilisez l'appareil natif.");
      return;
    }

    const mimeType = supportedVideoMimeType();
    recordedChunks = [];
    isStoppingRecording = false;
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
      isStoppingRecording = false;
      setRecordingState(false);
      showPreviewAfterCapture("Vidéo prête");
    });
    recorder.start();
    recordingStartedAt = Date.now();
    updateRecordingTimer();
    recordingInterval = setInterval(updateRecordingTimer, 200);
    recordingTimeout = setTimeout(stopVideoRecording, maxRecordingSeconds * 1000);
    setRecordingState(true);
    showCameraFeedback("Enregistrement", "recording");
    setCameraStatus("Vidéo en cours - stop pour terminer");
  }

  function stopVideoRecording() {
    if (isStoppingRecording) {
      return;
    }
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
    }
    if (recordingInterval) {
      clearInterval(recordingInterval);
      recordingInterval = null;
    }
    if (recorder && recorder.state !== "inactive") {
      isStoppingRecording = true;
      setCameraStatus("Vidéo en préparation...");
      showCameraFeedback("Préparation", "recording");
      updateCameraUi();
      recorder.stop();
    }
  }

  if (cameraStudio && (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)) {
    cameraStudio.classList.add("camera-studio--unsupported");
    setPermissionNote("Caméra intégrée indisponible. Utilisez l'appareil natif.", "warning");
  }
  refreshCameraPermissionHint();
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

  if (lensToggleButton) {
    lensToggleButton.addEventListener("click", function () {
      selectFacingMode(facingMode === "environment" ? "user" : "environment");
    });
  }

  if (modeToggleButton) {
    modeToggleButton.addEventListener("click", function () {
      if (recorder && recorder.state === "recording") {
        return;
      }
      cameraMode = cameraMode === "photo" ? "video" : "photo";
      setCameraStatus(cameraMode === "photo" ? "Mode photo - appuyez au centre" : "Mode vidéo - appuyez au centre");
      updateCameraUi();
    });
  }

  if (cameraActionButton) {
    cameraActionButton.addEventListener("click", function () {
      if (recorder && recorder.state === "recording") {
        stopVideoRecording();
        return;
      }
      if (cameraMode === "video") {
        startVideoRecording();
        return;
      }
      capturePhoto();
    });
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
      selectedFileName.textContent = file ? "Souvenir prêt : " + file.name : "JPG, PNG, WEBP, MP4, MOV ou WEBM.";

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
        previewDetails.textContent = sizeLabel ? "Aperçu prêt - " + sizeLabel + "." : "Aperçu prêt.";
      }

      if (previewBackdrop) {
        // Le fond floute evite les bandes noires autour d'une photo verticale,
        // comme dans le film final : l'invite revoit son cadrage, pas un recadrage.
        previewBackdrop.src = file.type.indexOf("image/") === 0 ? previewUrl : "";
      }

      if (file.type.indexOf("image/") === 0 && previewImage) {
        previewImage.src = previewUrl;
        previewImage.hidden = false;
        if (previewDetails) {
          const sizeLabel = formatFileSize(file.size);
          previewDetails.textContent = sizeLabel ? "Photo prête - " + sizeLabel + "." : "Photo prête.";
        }
        return;
      }

      if (file.type.indexOf("video/") === 0 && previewVideo) {
        previewVideo.src = previewUrl;
        previewVideo.hidden = false;
        if (previewDetails) {
          const sizeLabel = formatFileSize(file.size);
          previewDetails.textContent = sizeLabel ? "Vidéo prête - " + sizeLabel + "." : "Vidéo prête.";
        }
        previewVideo.addEventListener("loadedmetadata", function handleMetadata() {
          const duration = previewVideo.duration;
          if (duration && Number.isFinite(duration)) {
            setClientDuration(duration);
            if (previewDetails) {
              const sizeLabel = formatFileSize(file.size);
              const parts = ["Vidéo prête", formatDuration(duration), sizeLabel].filter(Boolean);
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
    retakeCameraButton.addEventListener("click", function () {
      closeCaptureReview();
      startCamera();
    });
  }

  if (useCaptureButton) {
    useCaptureButton.addEventListener("click", function () {
      closeCaptureReview();
      // On amene l'invite au choix du moment : l'etape qui lui reste a faire.
      const momentField = document.querySelector(".moment-field");
      if (momentField && momentField.scrollIntoView) {
        momentField.scrollIntoView({ block: "center" });
      }
    });
  }

  form.addEventListener("submit", function (event) {
    if (!window.XMLHttpRequest || !window.FormData) {
      return;
    }

    if (!form.checkValidity()) {
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
      progressText.textContent = "Préparation de l'envoi...";
    }
    slowUploadTimer = window.setTimeout(function () {
      if (progressText) {
        progressText.textContent = "Connexion lente... gardez cette page ouverte.";
      }
    }, 8000);
    verySlowUploadTimer = window.setTimeout(function () {
      if (progressText) {
        progressText.textContent = "Envoi toujours en cours. Les vidéos peuvent prendre plus de temps.";
      }
    }, 20000);

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
      clearTimeout(slowUploadTimer);
      clearTimeout(verySlowUploadTimer);
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
      clearTimeout(slowUploadTimer);
      clearTimeout(verySlowUploadTimer);
      if (progressText) {
        progressText.textContent = "L'envoi a échoué. Vérifiez la connexion puis réessayez.";
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
    });

    request.addEventListener("abort", function () {
      clearTimeout(slowUploadTimer);
      clearTimeout(verySlowUploadTimer);
      if (progressText) {
        progressText.textContent = "L'envoi a été interrompu.";
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
    });

    request.send(new FormData(form));
  });
})();
