(function () {
  const ACTIVE_STATUSES = new Set(["pending", "processing"]);
  const POLL_DELAY_MS = 5000;

  async function refreshGuestbookMoviePanel() {
    const panel = document.querySelector("[data-guestbook-movie-status-panel]");
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
        window.setTimeout(refreshGuestbookMoviePanel, POLL_DELAY_MS);
        return;
      }
      panel.outerHTML = await response.text();
    } catch (error) {
      window.setTimeout(refreshGuestbookMoviePanel, POLL_DELAY_MS);
      return;
    }

    window.setTimeout(refreshGuestbookMoviePanel, POLL_DELAY_MS);
  }

  window.setTimeout(refreshGuestbookMoviePanel, POLL_DELAY_MS);
})();
