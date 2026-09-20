// Secours quand la camera integree ne s'ouvre pas : l'appareil photo natif du
// telephone, en PHOTO uniquement. `capture` ouvre l'appareil photo (pas la
// galerie) et `accept="image/*"` exclut les videos : un souvenir doit etre pris
// sur le moment. La photo est confiee au champ principal du formulaire, ce qui
// reutilise tel quel l'apercu et l'envoi de upload-progress.js.
(function () {
  const button = document.getElementById("native-photo-button");
  const nativeInput = document.getElementById("native-photo-input");
  const error = document.getElementById("native-photo-error");
  const form = document.getElementById("guest-upload-form");
  const mainInput = form && form.querySelector("input[name='media_file']");
  if (!button || !nativeInput || !mainInput) {
    return;
  }

  // Sans camera integree, ce lien devient le moyen principal d'envoyer : on
  // retire le bloc camera (inutilisable) et le bouton perd sa forme de question.
  const studio = document.getElementById("camera-studio");
  if (studio && studio.classList.contains("camera-studio--unsupported")) {
    studio.hidden = true;
    button.textContent = "Prendre une photo avec le téléphone";
    button.closest(".native-photo").classList.add("native-photo--primary");
  }

  function showError(visible) {
    if (error) {
      error.hidden = !visible;
    }
  }

  button.addEventListener("click", function () {
    showError(false);
    nativeInput.click();
  });

  nativeInput.addEventListener("change", function () {
    const file = nativeInput.files && nativeInput.files[0];
    nativeInput.value = "";
    if (!file) {
      return;
    }
    if (!file.type || file.type.indexOf("image/") !== 0) {
      showError(true);
      return;
    }
    try {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      mainInput.files = transfer.files;
    } catch (exception) {
      showError(true);
      return;
    }
    showError(false);
    mainInput.dispatchEvent(new Event("change", { bubbles: true }));
  });
})();
