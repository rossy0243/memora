(function () {
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      const submitButton = form.querySelector("button[type='submit'][data-loading-text]");
      if (!submitButton) {
        return;
      }
      submitButton.disabled = true;
      submitButton.textContent = submitButton.dataset.loadingText || "Enregistrement...";
    });
  });
})();
