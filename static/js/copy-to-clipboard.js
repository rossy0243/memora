document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) {
      return;
    }

    const text = target.textContent.trim();
    try {
      await navigator.clipboard.writeText(text);
      const initialLabel = button.textContent;
      button.textContent = "Copie";
      window.setTimeout(() => {
        button.textContent = initialLabel;
      }, 1400);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
});
