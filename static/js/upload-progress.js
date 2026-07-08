(function () {
  const form = document.getElementById("guest-upload-form");
  if (!form) {
    return;
  }

  const progress = form.querySelector(".upload-progress");
  const progressBar = form.querySelector(".upload-progress__bar span");
  const submitButton = form.querySelector("button[type='submit']");

  form.addEventListener("submit", function () {
    if (progress) {
      progress.hidden = false;
    }
    if (progressBar) {
      progressBar.style.width = "35%";
      window.setTimeout(function () {
        progressBar.style.width = "75%";
      }, 300);
    }
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Envoi...";
    }
  });
})();
