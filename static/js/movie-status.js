(function () {
  const ACTIVE_STATUSES = new Set(["pending", "processing"]);
  const POLL_DELAY_MS = 5000;

  async function refreshMoviePanel() {
    const panel = document.querySelector("[data-movie-status-panel]");
    if (!panel) {
      return;
    }

    const status = panel.dataset.status;
    const url = panel.dataset.statusUrl;
    if (!url || !ACTIVE_STATUSES.has(status)) {
      return;
    }

    try {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        window.setTimeout(refreshMoviePanel, POLL_DELAY_MS);
        return;
      }
      panel.outerHTML = await response.text();
    } catch (error) {
      window.setTimeout(refreshMoviePanel, POLL_DELAY_MS);
      return;
    }

    window.setTimeout(refreshMoviePanel, POLL_DELAY_MS);
  }

  window.setTimeout(refreshMoviePanel, POLL_DELAY_MS);
})();
