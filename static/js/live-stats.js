(function () {
  const POLL_DELAY_MS = 25000;

  async function refreshLiveStats() {
    const panel = document.querySelector("[data-live-stats-panel]");
    if (!panel || panel.dataset.active !== "1") {
      return;
    }

    const url = panel.dataset.statusUrl;
    if (!url) {
      return;
    }

    try {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        window.setTimeout(refreshLiveStats, POLL_DELAY_MS);
        return;
      }
      panel.outerHTML = await response.text();
    } catch (error) {
      window.setTimeout(refreshLiveStats, POLL_DELAY_MS);
      return;
    }

    window.setTimeout(refreshLiveStats, POLL_DELAY_MS);
  }

  window.setTimeout(refreshLiveStats, POLL_DELAY_MS);
})();
