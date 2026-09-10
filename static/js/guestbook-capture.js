(function () {
  const form = document.getElementById("guestbook-form");
  if (!form) {
    return;
  }

  const fileInput = form.querySelector("input[type='file']");
  const clientDurationInput = document.getElementById("client-duration-seconds");
  const capturePreview = document.getElementById("capture-preview");
  const previewVideo = document.getElementById("capture-preview-video");
  const previewDetails = document.getElementById("capture-preview-details");
  const retakeCameraButton = document.getElementById("retake-camera-button");
  const captureErrors = document.querySelector(".capture-preview__errors");
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
  const cameraActionButton = document.getElementById("camera-action-button");
  const closeCameraButton = document.getElementById("close-camera-button");
  const progress = form.querySelector(".upload-progress");
  const progressBar = form.querySelector(".upload-progress__bar span");
  const progressText = form.querySelector(".upload-progress p");
  const submitButton = form.querySelector("button[type='submit']");
  const initialSubmitLabel = submitButton ? submitButton.textContent : "";
  const maxRecordingSeconds = (cameraStudio && parseInt(cameraStudio.dataset.maxDuration, 10)) || 30;

  let previewUrl = "";
  let cameraStream = null;
  // La tablette fait face a l'invite qui parle : selfie par defaut, a l'inverse
  // du parcours candide (qui filme les autres, donc camera arriere par defaut).
  let facingMode = "user";
  let recorder = null;
  let recordedChunks = [];
  let recordingTimeout = null;
  let recordingStartedAt = 0;
  let recordingInterval = null;
  let isSwitchingCamera = false;
  let isStoppingRecording = false;
  let slowUploadTimer = null;
  let verySlowUploadTimer = null;

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
    if (previewVideo) {
      previewVideo.pause();
      previewVideo.removeAttribute("src");
      previewVideo.load();
    }
    if (previewDetails) {
      previewDetails.textContent = "Vérifiez l'aperçu, ajoutez un nom si besoin, puis envoyez.";
    }
  }

  function setClientDuration(durationSeconds) {
    if (!clientDurationInput) {
      return;
    }
    clientDurationInput.value = durationSeconds && Number.isFinite(durationSeconds)
      ? Math.min(durationSeconds, maxRecordingSeconds).toFixed(2)
      : "";
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
    if (cameraActionButton) {
      cameraActionButton.classList.toggle("camera-shutter--stop", isRecording);
      cameraActionButton.classList.toggle("camera-shutter--stopping", isStoppingRecording);
      cameraActionButton.disabled = isStoppingRecording;
      cameraActionButton.setAttribute(
        "aria-label",
        isStoppingRecording ? "Préparation du message" : isRecording ? "Arrêter l'enregistrement" : "Lancer l'enregistrement",
      );
      const label = cameraActionButton.querySelector("strong");
      if (label) {
        label.textContent = isStoppingRecording ? "..." : isRecording ? "Stop" : "Vidéo";
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
      recordingTimer.textContent = maxRecordingSeconds + " s";
    }
    updateCameraUi();
  }

  function updateRecordingTimer() {
    if (!recordingTimer || !recordingStartedAt) {
      return;
    }
    // Compte a rebours : l'agent voit le temps restant fondre vers zero, jamais
    // une valeur figee. L'auto-stop coupe quand il atteint 0.
    const elapsed = (Date.now() - recordingStartedAt) / 1000;
    const remaining = Math.max(0, maxRecordingSeconds - elapsed);
    const remainingLabel = remaining.toFixed(remaining >= 10 ? 0 : 1).replace(".", ",");
    recordingTimer.textContent = remainingLabel + " s";
    setCameraStatus("Message en cours - stop pour terminer");
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
      return "La caméra n'a pas pu s'ouvrir. Réessayez dans quelques instants.";
    }
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Autorisez la caméra et le micro pour capturer avec Memora.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "Aucune caméra disponible sur cet appareil.";
    }
    if (error.name === "NotReadableError" || error.name === "TrackStartError") {
      return "La caméra est déjà utilisée par une autre application.";
    }
    if (error.name === "OverconstrainedError" || error.name === "ConstraintNotSatisfiedError") {
      return "Cet objectif n'est pas disponible sur cet appareil.";
    }
    return "La caméra n'a pas pu s'ouvrir. Réessayez dans quelques instants.";
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
        setPermissionNote("Le navigateur demandera l'autorisation caméra et micro.");
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
      setCameraStatus("Caméra intégrée indisponible sur ce navigateur.");
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

  function setCapturedFile(blob, filename) {
    if (!fileInput || !window.DataTransfer || !window.File) {
      setCameraStatus("Message prêt, mais le navigateur ne peut pas l'attacher au formulaire.");
      return;
    }
    const file = new File([blob], filename, { type: blob.type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    setCameraStatus("Message prêt à envoyer");
  }

  function openCaptureReview() {
    document.body.classList.add("capture-review-open");
  }

  function closeCaptureReview() {
    document.body.classList.remove("capture-review-open");
  }

  function showPreviewAfterCapture(message) {
    showCameraFeedback(message, "success");
    stopCamera();
    openCaptureReview();
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
      setCameraStatus("Enregistrement vidéo indisponible sur ce navigateur.");
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
      setCapturedFile(blob, "livre-dor-" + timestamp() + "." + extension);
      setClientDuration(recordedSeconds);
      recordedChunks = [];
      recordingStartedAt = 0;
      isStoppingRecording = false;
      setRecordingState(false);
      showPreviewAfterCapture("Message enregistré");
    });
    recorder.start();
    recordingStartedAt = Date.now();
    updateRecordingTimer();
    recordingInterval = setInterval(updateRecordingTimer, 200);
    recordingTimeout = setTimeout(stopVideoRecording, maxRecordingSeconds * 1000);
    setRecordingState(true);
    showCameraFeedback("Enregistrement", "recording");
    setCameraStatus("Message en cours - stop pour terminer");
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
      setCameraStatus("Message en préparation...");
      showCameraFeedback("Préparation", "recording");
      updateCameraUi();
      recorder.stop();
    }
  }

  if (cameraStudio && (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)) {
    cameraStudio.classList.add("camera-studio--unsupported");
    setPermissionNote("Caméra intégrée indisponible sur ce navigateur.", "warning");
  }
  refreshCameraPermissionHint();
  updateCameraUi();

  if (startCameraButton) {
    startCameraButton.addEventListener("click", function () {
      startCamera();
    });
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

  if (cameraActionButton) {
    cameraActionButton.addEventListener("click", function () {
      if (recorder && recorder.state === "recording") {
        stopVideoRecording();
        return;
      }
      startVideoRecording();
    });
  }

  if (closeCameraButton) {
    closeCameraButton.addEventListener("click", stopCamera);
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      const file = fileInput.files && fileInput.files[0];
      clearPreview();
      if (!file || !capturePreview || !window.URL || !URL.createObjectURL) {
        return;
      }

      previewUrl = URL.createObjectURL(file);
      capturePreview.hidden = false;
      if (previewVideo) {
        previewVideo.src = previewUrl;
        previewVideo.muted = true;
        previewVideo.loop = true;
        previewVideo.autoplay = true;
        previewVideo.playsInline = true;
        previewVideo.setAttribute("muted", "");
        previewVideo.addEventListener("loadedmetadata", function handleMetadata() {
          const duration = previewVideo.duration;
          if (duration && Number.isFinite(duration)) {
            setClientDuration(duration);
            if (previewDetails) {
              const sizeLabel = formatFileSize(file.size);
              const parts = ["Message prêt", formatDuration(duration), sizeLabel].filter(Boolean);
              previewDetails.textContent = parts.join(" - ") + ".";
            }
          }
          const playback = previewVideo.play();
          if (playback && playback.catch) {
            playback.catch(function () {
              try {
                previewVideo.currentTime = 0.05;
              } catch (error) {
                /* certains navigateurs refusent le seek avant lecture : sans gravite */
              }
            });
          }
        }, { once: true });
        previewVideo.load();
      }
    });
  }

  if (retakeCameraButton) {
    retakeCameraButton.addEventListener("click", function () {
      closeCaptureReview();
      startCamera();
    });
  }

  function extractServerErrorMessages(responseText) {
    try {
      const doc = new DOMParser().parseFromString(responseText || "", "text/html");
      const items = doc.querySelectorAll(".errorlist li");
      return Array.prototype.map
        .call(items, function (item) {
          return item.textContent.trim();
        })
        .filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  function showCaptureErrors(errorMessages) {
    if (!captureErrors) {
      return;
    }
    captureErrors.innerHTML = "";
    const list = errorMessages && errorMessages.length ? errorMessages : ["L'envoi a échoué. Réessayez."];
    list.forEach(function (message) {
      const item = document.createElement("li");
      item.textContent = message;
      captureErrors.appendChild(item);
    });
    captureErrors.hidden = false;
  }

  function clearCaptureErrors() {
    if (!captureErrors) {
      return;
    }
    captureErrors.hidden = true;
    captureErrors.innerHTML = "";
  }

  form.addEventListener("submit", function (event) {
    if (!window.XMLHttpRequest || !window.FormData) {
      return;
    }
    if (!form.checkValidity()) {
      return;
    }

    event.preventDefault();

    clearCaptureErrors();
    if (retakeCameraButton) {
      retakeCameraButton.disabled = true;
    }
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
        progressText.textContent = "Envoi toujours en cours.";
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

    function finishFailedSend(errorMessages) {
      clearTimeout(slowUploadTimer);
      clearTimeout(verySlowUploadTimer);
      if (progress) {
        progress.hidden = true;
      }
      showCaptureErrors(errorMessages);
      if (retakeCameraButton) {
        retakeCameraButton.disabled = false;
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
    }

    request.addEventListener("load", function () {
      // L'envoi reussi redirige vers la MEME page (ecran pret pour l'invite
      // suivant) : contrairement au parcours invite, l'URL ne suffit pas a
      // distinguer un succes d'un formulaire invalide. On se fie plutot a la
      // presence (ou non) d'erreurs dans la reponse.
      const errorMessages = extractServerErrorMessages(request.responseText);
      if (request.status >= 200 && request.status < 300 && errorMessages.length === 0) {
        clearTimeout(slowUploadTimer);
        clearTimeout(verySlowUploadTimer);
        if (progressBar) {
          progressBar.style.width = "100%";
        }
        window.location.assign(form.action);
        return;
      }

      finishFailedSend(errorMessages);
    });

    request.addEventListener("error", function () {
      finishFailedSend(["L'envoi a échoué. Vérifiez la connexion puis réessayez."]);
    });

    request.addEventListener("abort", function () {
      finishFailedSend(["L'envoi a été interrompu."]);
    });

    request.send(new FormData(form));
  });
})();
