(function () {
  const form = document.getElementById("guest-upload-form");
  if (!form) {
    return;
  }

  const fileInput = form.querySelector("input[type='file']");
  const selectedFileName = document.getElementById("selected-file-name");
  const capturePreview = document.getElementById("capture-preview");
  const previewImage = document.getElementById("capture-preview-image");
  const previewVideo = document.getElementById("capture-preview-video");
  const replaceMediaButton = document.getElementById("replace-media-button");
  const cameraStudio = document.getElementById("camera-studio");
  const startCameraButton = document.getElementById("start-camera-button");
  const cameraPanel = document.getElementById("camera-panel");
  const liveVideo = document.getElementById("camera-live-video");
  const cameraStatus = document.getElementById("camera-status");
  const switchCameraButton = document.getElementById("switch-camera-button");
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
  }

  function setCameraStatus(message) {
    if (cameraStatus) {
      cameraStatus.textContent = message;
    }
  }

  function stopCamera() {
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
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
    if (cameraPanel) {
      cameraPanel.hidden = true;
    }
    if (recordVideoButton) {
      recordVideoButton.hidden = false;
    }
    if (stopVideoButton) {
      stopVideoButton.hidden = true;
    }
  }

  async function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !liveVideo) {
      if (cameraStudio) {
        cameraStudio.classList.add("camera-studio--unsupported");
      }
      setCameraStatus("Camera integree indisponible. Utilisez l'appareil natif.");
      return;
    }

    stopCamera();
    setCameraStatus("Ouverture de la camera...");
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      liveVideo.srcObject = cameraStream;
      liveVideo.style.filter = cameraFilters[activeFilter] || "none";
      if (cameraPanel) {
        cameraPanel.hidden = false;
      }
      setCameraStatus(facingMode === "user" ? "Mode selfie" : "Camera arriere");
    } catch {
      setCameraStatus("Autorisez la camera ou utilisez l'appareil natif.");
    }
  }

  function timestamp() {
    return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
  }

  function setCapturedFile(blob, filename) {
    if (!fileInput || !window.DataTransfer || !window.File) {
      setCameraStatus("Capture prete. Votre navigateur demande l'appareil natif.");
      return;
    }

    const file = new File([blob], filename, { type: blob.type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    setCameraStatus("Souvenir pret a envoyer");
  }

  function capturePhoto() {
    if (!liveVideo || !cameraStream) {
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = liveVideo.videoWidth || 1280;
    canvas.height = liveVideo.videoHeight || 720;
    const context = canvas.getContext("2d");
    context.filter = cameraFilters[activeFilter] || "none";
    context.drawImage(liveVideo, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      if (blob) {
        setCapturedFile(blob, "memora-photo-" + timestamp() + ".jpg");
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
      const recordedType = recorder.mimeType || mimeType || "video/webm";
      const extension = recordedType.indexOf("mp4") >= 0 ? "mp4" : "webm";
      const blob = new Blob(recordedChunks, { type: recordedType });
      setCapturedFile(blob, "memora-video-" + timestamp() + "." + extension);
      recordedChunks = [];
    });
    recorder.start();
    recordingTimeout = setTimeout(stopVideoRecording, maxRecordingSeconds * 1000);
    setCameraStatus("Enregistrement video... 10 secondes max");
    if (recordVideoButton) {
      recordVideoButton.hidden = true;
    }
    if (stopVideoButton) {
      stopVideoButton.hidden = false;
    }
  }

  function stopVideoRecording() {
    if (recordingTimeout) {
      clearTimeout(recordingTimeout);
      recordingTimeout = null;
    }
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    if (recordVideoButton) {
      recordVideoButton.hidden = false;
    }
    if (stopVideoButton) {
      stopVideoButton.hidden = true;
    }
  }

  if (cameraStudio && (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)) {
    cameraStudio.classList.add("camera-studio--unsupported");
  }

  if (startCameraButton) {
    startCameraButton.addEventListener("click", startCamera);
  }

  if (switchCameraButton) {
    switchCameraButton.addEventListener("click", function () {
      facingMode = facingMode === "environment" ? "user" : "environment";
      switchCameraButton.textContent = facingMode === "environment" ? "Selfie" : "Arriere";
      startCamera();
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
      if (!file || !capturePreview || !window.URL || !URL.createObjectURL) {
        return;
      }

      previewUrl = URL.createObjectURL(file);
      capturePreview.hidden = false;

      if (file.type.indexOf("image/") === 0 && previewImage) {
        previewImage.src = previewUrl;
        previewImage.hidden = false;
        return;
      }

      if (file.type.indexOf("video/") === 0 && previewVideo) {
        previewVideo.src = previewUrl;
        previewVideo.hidden = false;
        previewVideo.load();
      }
    });
  }

  if (replaceMediaButton && fileInput) {
    replaceMediaButton.addEventListener("click", function () {
      fileInput.click();
    });
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
