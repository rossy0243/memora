document.querySelectorAll("[data-share-url]").forEach((button) => {
  button.addEventListener("click", async () => {
    const url = button.dataset.shareUrl;
    const title = button.dataset.shareTitle || document.title;
    if (!url) {
      return;
    }

    if (navigator.share) {
      try {
        await navigator.share({ title, url });
        return;
      } catch {
        // The user may cancel the native share sheet.
      }
    }

    try {
      await navigator.clipboard.writeText(url);
      const initialLabel = button.textContent;
      button.textContent = "Lien copié";
      window.setTimeout(() => {
        button.textContent = initialLabel;
      }, 1400);
    } catch {
      window.prompt("Copiez ce lien", url);
    }
  });
});
