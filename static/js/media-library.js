(function () {
  const grid = document.getElementById("media-library-grid");
  if (!grid) {
    return;
  }

  // Delegation sur la grille (pas sur chaque formulaire) : une carte remplacee par
  // le fetch garde son ecouteur sans avoir besoin d'etre re-attachee.
  grid.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-media-action]");
    if (!form) {
      return;
    }
    event.preventDefault();

    const submitButton = form.querySelector("button[type=submit]");
    if (submitButton) {
      submitButton.disabled = true;
    }

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();

      const card = grid.querySelector(`[data-upload-id="${data.upload_id}"]`);
      if (card) {
        if (data.action === "remove") {
          card.remove();
        } else if (data.action === "replace" && data.html) {
          card.outerHTML = data.html;
        }
      }

      const movieSummary = document.getElementById("media-movie-summary");
      if (movieSummary && data.movie_summary_html) {
        movieSummary.innerHTML = data.movie_summary_html;
      }
      const teaserSummary = document.getElementById("media-teaser-summary");
      if (teaserSummary && data.teaser_summary_html) {
        teaserSummary.innerHTML = data.teaser_summary_html;
      }
    } catch (error) {
      // Repli : le geste rapide a echoue (reseau, session expiree...) — on retombe
      // sur le comportement d'origine (rechargement complet) plutot que de laisser
      // l'organisateur croire que son clic n'a rien fait.
      form.submit();
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  });
})();
