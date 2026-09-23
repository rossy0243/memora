(function () {
  const form = document.getElementById("guest-upload-form");
  if (!form) {
    return;
  }

  const fileInput = form.querySelector("input[type='file']");
  const clientDurationInput = document.getElementById("client-duration-seconds");
  const capturePreview = document.getElementById("capture-preview");
  const previewImage = document.getElementById("capture-preview-image");
  const previewVideo = document.getElementById("capture-preview-video");
  const previewDetails = document.getElementById("capture-preview-details");
  const retakeCameraButton = document.getElementById("retake-camera-button");
  const captureErrors = document.querySelector(".capture-preview__errors");
  const previewBackdrop = document.getElementById("capture-preview-backdrop");
  const cameraStudio = document.getElementById("camera-studio");
  const startCameraPhotoButton = document.getElementById("start-camera-photo-button");
  const startCameraVideoButton = document.getElementById("start-camera-video-button");
  const cameraPanel = document.getElementById("camera-panel");
  const cameraPermissionNote = document.getElementById("camera-permission-note");
  const liveVideo = document.getElementById("camera-live-video");
  const cameraStatus = document.getElementById("camera-status");
  const cameraFeedback = document.getElementById("camera-feedback");
  const recordingBadge = document.getElementById("camera-recording-badge");
  const recordingTimer = document.getElementById("camera-recording-timer");
  const lensToggleButton = document.getElementById("lens-toggle-button");
  const modeToggleButton = document.getElementById("mode-toggle-button");
  const flashToggleButton = document.getElementById("flash-toggle-button");
  const cameraActionButton = document.getElementById("camera-action-button");
  const closeCameraButton = document.getElementById("close-camera-button");
  const progress = form.querySelector(".upload-progress");
  const progressBar = form.querySelector(".upload-progress__bar span");
  const progressText = form.querySelector(".upload-progress p");
  const submitButton = form.querySelector("button[type='submit']");
  const quotaBox = document.getElementById("upload-quota");
  const quotaText = document.getElementById("upload-quota-text");
  const quotaDots = document.querySelectorAll("#upload-quota-dots i");
  const quotaFinish = document.getElementById("upload-quota-finish");
  const cameraSentCount = document.getElementById("camera-sent-count");
  const initialSubmitLabel = submitButton ? submitButton.textContent : "";
  let previewUrl = "";
  let retryPreviewUrl = "";
  let lastRecorderType = "";
  let previewToken = 0;
  let cameraStream = null;
  let facingMode = "environment";
  let flashOn = false;
  let flashSupported = false;
  let recorder = null;
  let recordedChunks = [];
  let recordingTimeout = null;
  let recordingStartedAt = 0;
  let recordingInterval = null;
  let pendingCapturedDuration = null;
  let pendingPoster = "";
  let previewPlaybackTimer = null;
  let cameraMode = "photo";
  let isSwitchingCamera = false;
  let isStoppingRecording = false;
  const maxRecordingSeconds = 10;
  // Envois reussis depuis cette page, et envois encore permis : la page reste en
  // camera entre deux souvenirs au lieu de se recharger.
  let sentCount = 0;
  let remainingUploads = parseInt(form.dataset.remaining, 10);
  let slowUploadTimer = null;
  let verySlowUploadTimer = null;

  function resetPreviewUrl() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }
    if (retryPreviewUrl) {
      URL.revokeObjectURL(retryPreviewUrl);
      retryPreviewUrl = "";
    }
  }

  // Rapport technique envoye au serveur quand le telephone n'arrive pas a relire son
  // propre enregistrement : type reel, code d'erreur, formats connus du navigateur.
  // Sert a comprendre les cas rares (iPhone) ; rien de personnel n'est envoye.
  function reportPreviewProblem(file, stage) {
    const url = form.dataset.diagnosticUrl;
    if (!url || !window.fetch || !window.FormData || !previewVideo) {
      return;
    }
    try {
      const recorderSupport = {};
      [
        "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
        "video/mp4",
        "video/webm;codecs=vp9",
        "video/webm;codecs=vp8",
        "video/webm",
      ].forEach(function (type) {
        recorderSupport[type] =
          window.MediaRecorder && MediaRecorder.isTypeSupported ? MediaRecorder.isTypeSupported(type) : null;
      });
      const report = {
        stage: stage,
        fileType: file.type,
        size: file.size,
        recorderType: lastRecorderType,
        videoError: previewVideo.error ? previewVideo.error.code + ":" + (previewVideo.error.message || "") : null,
        readyState: previewVideo.readyState,
        networkState: previewVideo.networkState,
        duration: String(previewVideo.duration),
        canPlay: {
          mp4: previewVideo.canPlayType("video/mp4"),
          webm: previewVideo.canPlayType("video/webm"),
          h264: previewVideo.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
        },
        recorderSupport: recorderSupport,
        ua: navigator.userAgent,
      };
      const data = new FormData();
      data.append("report", JSON.stringify(report));
      const token = form.querySelector("[name=csrfmiddlewaretoken]");
      if (token) {
        data.append("csrfmiddlewaretoken", token.value);
      }
      window.fetch(url, { method: "POST", body: data, keepalive: true, credentials: "same-origin" }).catch(function () {});
    } catch (error) {
      /* le rapport est facultatif */
    }
  }

  function clearPreview() {
    previewToken += 1;
    resetPreviewUrl();
    closeCaptureReview();
    if (capturePreview) {
      capturePreview.hidden = true;
      capturePreview.classList.remove("capture-preview--photo");
    }
    if (previewBackdrop) {
      previewBackdrop.removeAttribute("src");
    }
    if (previewImage) {
      previewImage.removeAttribute("src");
      previewImage.hidden = true;
    }
    if (previewPlaybackTimer) {
      window.clearTimeout(previewPlaybackTimer);
      previewPlaybackTimer = null;
    }
    if (previewVideo) {
      previewVideo.pause();
      previewVideo.removeAttribute("src");
      previewVideo.removeAttribute("poster");
      previewVideo.controls = false;
      previewVideo.hidden = true;
      previewVideo.load();
    }
    if (previewDetails) {
      previewDetails.textContent = "Vérifiez l'aperçu, puis envoyez.";
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
    if (!isRecording && cameraActionButton) {
      cameraActionButton.style.setProperty("--rec-progress", "0");
    }
    updateCameraUi();
  }

  function updateRecordingTimer() {
    if (!recordingTimer || !recordingStartedAt) {
      return;
    }
    const elapsed = Math.min((Date.now() - recordingStartedAt) / 1000, maxRecordingSeconds);
    // Le "/ 10 s" pousse naturellement vers le chemin le plus court : laisser
    // l'auto-stop couper au lieu de chercher le bouton pour arreter soi-meme.
    if (cameraActionButton) {
      cameraActionButton.style.setProperty("--rec-progress", String(elapsed / maxRecordingSeconds));
    }
    const elapsedLabel = elapsed.toFixed(elapsed >= 10 ? 0 : 1).replace(".", ",");
    recordingTimer.textContent = elapsedLabel + " / " + maxRecordingSeconds + " s";
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
      return "Cet objectif n'est pas disponible sur ce téléphone.";
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
        setPermissionNote("L'accès caméra et micro vous sera demandé.");
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

  // Flash / torche : uniquement disponible sur certains telephones Android, avec la camera
  // arriere (jamais en selfie). On decouvre la capacite APRES coup, sur le flux obtenu — la
  // demande initiale ne doit jamais echouer a cause d'un flash absent.
  function currentVideoTrack() {
    return cameraStream ? cameraStream.getVideoTracks()[0] : null;
  }

  function updateFlashUi() {
    if (!flashToggleButton) {
      return;
    }
    flashToggleButton.hidden = !flashSupported;
    flashToggleButton.classList.toggle("is-active", flashOn);
    flashToggleButton.setAttribute("aria-pressed", flashOn ? "true" : "false");
    flashToggleButton.setAttribute("aria-label", flashOn ? "Éteindre le flash" : "Allumer le flash");
  }

  function detectFlashSupport() {
    flashOn = false;
    flashSupported = false;
    const track = currentVideoTrack();
    if (track && typeof track.getCapabilities === "function") {
      try {
        const capabilities = track.getCapabilities();
        flashSupported = !!(capabilities && capabilities.torch);
      } catch {
        // Certains navigateurs (Safari iOS) n'exposent pas les capacites : le bouton reste cache.
      }
    }
    updateFlashUi();
  }

  async function setFlash(nextFlashOn) {
    const track = currentVideoTrack();
    if (!track || !flashSupported) {
      return;
    }
    try {
      await track.applyConstraints({ advanced: [{ torch: nextFlashOn }] });
      flashOn = nextFlashOn;
    } catch {
      // Le telephone a refuse la commande (torche coupee par le systeme...) : l'etat ne change pas.
    }
    updateFlashUi();
  }

  if (flashToggleButton) {
    flashToggleButton.addEventListener("click", function () {
      setFlash(!flashOn);
    });
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
    // La torche s'eteint avec la piste qui la pilotait : l'etat affiche doit suivre.
    flashOn = false;
    flashSupported = false;
    updateFlashUi();
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
      detectFlashSupport();
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
      setCameraStatus("Capture prête, mais le navigateur ne peut pas l'attacher au formulaire.");
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

  // Sur iPhone, une video chargee dans un element pas encore affiche (ou en mode
  // economie d'energie) ne demarre pas seule et reste NOIRE. Des que la revue est
  // visible, on relance la lecture ; sinon on affiche les commandes natives.
  function retryPreviewPlayback() {
    if (!previewVideo || previewVideo.hidden || !previewVideo.getAttribute("src")) {
      return;
    }
    const playback = previewVideo.play();
    if (playback && playback.catch) {
      playback.catch(function () {
        previewVideo.controls = true;
      });
    }
  }

  // Derniere image du viseur, utilisee comme affiche de la video : meme si le
  // telephone ne sait pas relire son propre enregistrement, l'invite voit son plan.
  function captureLiveFrame() {
    try {
      if (!liveVideo || !liveVideo.videoWidth) {
        return "";
      }
      const canvas = document.createElement("canvas");
      const scale = Math.min(1, 960 / liveVideo.videoWidth);
      canvas.width = Math.round(liveVideo.videoWidth * scale);
      canvas.height = Math.round(liveVideo.videoHeight * scale);
      canvas.getContext("2d").drawImage(liveVideo, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/jpeg", 0.85);
    } catch (error) {
      return "";
    }
  }

  function showPreviewAfterCapture(message) {
    showCameraFeedback(message, "success");
    // On reste en plein ecran : l'image capturee remplace le flux au meme endroit,
    // comme une vraie camera. Pas d'attente, pas de sortie, pas de defilement.
    // stopCamera libere la camera et masque le panneau dans le meme tick que
    // l'ouverture de la revue : le navigateur ne peint jamais la page intermediaire.
    stopCamera();
    openCaptureReview();
    retryPreviewPlayback();
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

  // Safari sur iPhone/iPad (tous les navigateurs iOS reposent sur WebKit) sait
  // ENREGISTRER en WebM/VP9 depuis iOS 18.4, mais ne relit pas toujours ce fichier
  // dans <video> : apercu noir, alors que la video est bien capturee. On lui
  // demande donc du MP4 (H.264/AAC), que ses lecteurs decodent toujours.
  function prefersMp4Recording() {
    const ua = navigator.userAgent || "";
    const isIos = /iP(hone|ad|od)/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    const isDesktopSafari = /Safari/.test(ua) && !/Chrom(e|ium)|Android|CriOS|FxiOS|Edg/.test(ua);
    return isIos || isDesktopSafari;
  }

  function supportedVideoMimeType() {
    if (!window.MediaRecorder) {
      return "";
    }
    const webm = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    const mp4 = ["video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4;codecs=avc1", "video/mp4"];
    const candidates = prefersMp4Recording() ? mp4.concat(webm) : webm.concat(mp4);
    return candidates.find(function (candidate) {
      return MediaRecorder.isTypeSupported(candidate);
    }) || "";
  }

  function startVideoRecording() {
    if (!cameraStream || !window.MediaRecorder) {
      setCameraStatus("Vidéo intégrée indisponible sur ce navigateur.");
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
      lastRecorderType = (mimeType || "(defaut)") + " -> " + (recorder.mimeType || "?");
      const extension = recordedType.indexOf("mp4") >= 0 ? "mp4" : "webm";
      const blob = new Blob(recordedChunks, { type: recordedType });
      pendingPoster = captureLiveFrame();
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
    setPermissionNote("Caméra intégrée indisponible sur ce navigateur.", "warning");
  }
  refreshCameraPermissionHint();
  updateCameraUi();

  function startCameraInMode(mode) {
    return function () {
      cameraMode = mode;
      updateCameraUi();
      startCamera();
    };
  }

  if (startCameraPhotoButton) {
    startCameraPhotoButton.addEventListener("click", startCameraInMode("photo"));
  }
  if (startCameraVideoButton) {
    startCameraVideoButton.addEventListener("click", startCameraInMode("video"));
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

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      const file = fileInput.files && fileInput.files[0];

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

      const isImage = file.type.indexOf("image/") === 0;
      const isVideo = file.type.indexOf("video/") === 0;

      // Le fond floute (et sa classe CSS) ne concernent que les photos.
      if (capturePreview) {
        capturePreview.classList.toggle("capture-preview--photo", isImage);
      }
      if (previewBackdrop) {
        if (isImage) {
          previewBackdrop.src = previewUrl;
        } else {
          previewBackdrop.removeAttribute("src");
        }
      }

      if (isImage && previewImage) {
        previewImage.src = previewUrl;
        previewImage.hidden = false;
        if (previewDetails) {
          const sizeLabel = formatFileSize(file.size);
          previewDetails.textContent = sizeLabel ? "Photo prête - " + sizeLabel + "." : "Photo prête.";
        }
        return;
      }

      if (isVideo && previewVideo) {
        const token = ++previewToken;
        const poster = pendingPoster;
        pendingPoster = "";
        const sizeLabel = formatFileSize(file.size);
        // Image d'affiche : visible tant que la lecture n'a pas demarre, et pour de bon si
        // le telephone ne relit pas son enregistrement (jamais d'ecran noir).
        if (poster) {
          previewVideo.poster = poster;
        }
        previewVideo.controls = false;
        previewVideo.src = previewUrl;
        previewVideo.hidden = false;
        previewVideo.muted = true;
        previewVideo.loop = true;
        previewVideo.autoplay = true;
        previewVideo.playsInline = true;
        previewVideo.preload = "auto";
        previewVideo.setAttribute("muted", "");
        if (previewDetails) {
          previewDetails.textContent = sizeLabel ? "Vidéo prête - " + sizeLabel + "." : "Vidéo prête.";
        }
        previewVideo.addEventListener("loadedmetadata", function handleMetadata() {
          if (token !== previewToken) {
            return;
          }
          const duration = previewVideo.duration;
          if (duration && Number.isFinite(duration)) {
            setClientDuration(duration);
            if (previewDetails) {
              const parts = ["Vidéo prête", formatDuration(duration), sizeLabel].filter(Boolean);
              previewDetails.textContent = parts.join(" - ") + ".";
            }
          }
          retryPreviewPlayback();
        }, { once: true });
        previewVideo.addEventListener("playing", function handlePlaying() {
          if (token !== previewToken) {
            return;
          }
          if (previewPlaybackTimer) {
            window.clearTimeout(previewPlaybackTimer);
            previewPlaybackTimer = null;
          }
          previewVideo.controls = false;
          if (previewDetails) {
            const played = ["Vidéo prête", formatDuration(previewVideo.duration), sizeLabel].filter(Boolean).join(" - ");
            previewDetails.textContent = previewVideo.muted ? played + ". Touchez la vidéo pour le son." : played + ".";
          }
        });
        // Filet de securite. Si le telephone ne lit pas l'enregistrement, on retente une
        // fois avec un type MIME simple (certains navigateurs refusent « ...;codecs=... »),
        // puis on garde l'image d'affiche, on propose les commandes natives (un toucher
        // suffit parfois a debloquer la lecture sur iPhone) et on le dit clairement. Le
        // fichier, lui, est bien capture et peut etre envoye.
        let retried = false;
        function retryWithPlainType() {
          retried = true;
          const plainType = file.type.indexOf("mp4") >= 0 ? "video/mp4" : "video/webm";
          retryPreviewUrl = URL.createObjectURL(new Blob([file], { type: plainType }));
          previewVideo.src = retryPreviewUrl;
          previewVideo.load();
        }
        let settled = false;
        function explainUnreadablePreview(stage) {
          if (settled || token !== previewToken || !previewVideo.getAttribute("src") || !previewDetails) {
            return;
          }
          if (previewVideo.error) {
            stage = "error";
          }
          if (previewVideo.readyState > 0) {
            if (previewVideo.paused) {
              previewVideo.controls = true;
              previewDetails.textContent = "Vidéo prête" + (sizeLabel ? " - " + sizeLabel : "") + ". Touchez ▶ pour la revoir.";
            }
            return;
          }
          previewVideo.controls = stage === "timeout";
          if (stage === "timeout") {
            previewDetails.textContent = "Vidéo prête" + (sizeLabel ? " - " + sizeLabel : "") + ". Touchez ▶ pour la revoir.";
          } else {
            previewDetails.textContent =
              "Aperçu animé indisponible sur cet appareil, mais la vidéo est bien enregistrée" +
              (sizeLabel ? " (" + sizeLabel + ")" : "") + ". Vous pouvez l'envoyer.";
          }
          if (/[?&]debug=1/.test(window.location.search)) {
            const code = previewVideo.error ? previewVideo.error.code : "-";
            previewDetails.textContent += " [" + (file.type || "?") + " erreur=" + code + "]";
          }
          if (stage === "error") {
            settled = true;
          }
          reportPreviewProblem(file, stage);
        }
        previewVideo.addEventListener("error", function handleError() {
          if (token !== previewToken) {
            return;
          }
          if (!retried) {
            retryWithPlainType();
            return;
          }
          explainUnreadablePreview("error");
        });
        previewPlaybackTimer = window.setTimeout(function () {
          explainUnreadablePreview("timeout");
        }, 2500);
        previewVideo.load();
      }
    });
  }

  if (previewVideo) {
    previewVideo.addEventListener("click", function () {
      if (previewVideo.controls) {
        return;
      }
      if (previewVideo.paused) {
        previewVideo.muted = false; // geste de l'invite : le son est autorise
      } else {
        previewVideo.muted = !previewVideo.muted;
      }
      retryPreviewPlayback();
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

  function showCaptureErrors(messages) {
    if (!captureErrors) {
      return;
    }
    captureErrors.innerHTML = "";
    const list = messages && messages.length ? messages : ["L'envoi a échoué. Réessayez."];
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

  // Compteur d'envois : meme texte que celui du serveur (guest_upload_form.html).
  function updateSentUi() {
    const limit = quotaBox ? parseInt(quotaBox.dataset.limit, 10) : NaN;
    const used = Number.isFinite(limit) ? limit - remainingUploads : sentCount;
    if (quotaBox && quotaText && Number.isFinite(limit)) {
      quotaText.textContent =
        remainingUploads === 1
          ? "Plus qu'un envoi"
          : remainingUploads === 2
            ? "Plus que 2 envois"
            : used + " souvenir" + (used > 1 ? "s envoyés" : " envoyé") + " sur " + limit;
    }
    quotaDots.forEach(function (dot, index) {
      dot.classList.toggle("is-used", index < used);
    });
    if (quotaFinish) {
      quotaFinish.hidden = used < 1;
    }
    if (cameraSentCount) {
      cameraSentCount.textContent = Number.isFinite(limit) ? "✓ " + used + " sur " + limit : "✓ " + sentCount + " envoyé" + (sentCount > 1 ? "s" : "");
      cameraSentCount.hidden = false;
    }
  }

  form.addEventListener("submit", function (event) {
    if (!window.XMLHttpRequest || !window.FormData) {
      return;
    }

    if (!form.checkValidity()) {
      return;
    }

    event.preventDefault();

    // La revue plein ecran reste ouverte : l'invite voit l'envoi se terminer
    // sans quitter l'aperçu de son souvenir, quelle que soit l'issue.
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

    // Un seul chemin de sortie en cas d'echec, quelle qu'en soit la cause :
    // la revue reste ouverte, le message apparait au meme endroit, et
    // l'invite peut reprendre ou retenter sans jamais perdre sa capture.
    function finishFailedSend(messages) {
      clearTimeout(slowUploadTimer);
      clearTimeout(verySlowUploadTimer);
      if (progress) {
        progress.hidden = true;
      }
      showCaptureErrors(messages);
      if (retakeCameraButton) {
        retakeCameraButton.disabled = false;
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
    }

    // Souvenir envoye et il en reste : on vide l'apercu et on rouvre la camera,
    // avec une confirmation et un compteur. Aucun rechargement de page.
    function finishSuccessfulSend() {
      if (progress) {
        progress.hidden = true;
      }
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = initialSubmitLabel;
      }
      if (retakeCameraButton) {
        retakeCameraButton.disabled = false;
      }
      clearPreview();
      fileInput.value = "";
      setClientDuration(null);
      updateSentUi();
      startCamera();
      showCameraFeedback("Envoyé ✓", "success");
    }

    request.addEventListener("load", function () {
      const responseUrl = request.responseURL || form.action;
      const currentAction = new URL(form.action, window.location.href).href;

      if (request.status >= 200 && request.status < 300 && responseUrl !== currentAction) {
        clearTimeout(slowUploadTimer);
        clearTimeout(verySlowUploadTimer);
        if (progressBar) {
          progressBar.style.width = "100%";
        }
        sentCount += 1;
        remainingUploads -= 1;
        // Plus d'envoi possible (ou pas de compteur fiable) : la page de
        // remerciement conclut. Sinon on reste en camera pour le souvenir suivant.
        if (!(remainingUploads > 0) || !window.DataTransfer) {
          window.location.assign(responseUrl);
          return;
        }
        finishSuccessfulSend();
        return;
      }

      finishFailedSend(extractServerErrorMessages(request.responseText));
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
