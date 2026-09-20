// Page « rendez-vous le jour J » laissee ouverte : elle se recharge toute seule a
// l'ouverture de la collecte, et le meme lien mene alors a la prise de photo ou de
// video. Un telephone en veille ne garde pas ses minuteries : on revérifie aussi
// quand l'invite revient sur la page.
(function () {
  const content = document.querySelector("[data-opens-at]");
  if (!content) {
    return;
  }
  const opensAt = new Date(content.dataset.opensAt).getTime();
  if (!Number.isFinite(opensAt)) {
    return;
  }

  function reloadIfOpen() {
    if (Date.now() >= opensAt) {
      window.location.reload();
    }
  }

  const delay = opensAt - Date.now();
  // setTimeout plafonne a ~24,8 jours ; au-dela, le retour sur la page suffit.
  if (delay > 0 && delay < 2147483647) {
    window.setTimeout(reloadIfOpen, delay + 1500);
  }
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      reloadIfOpen();
    }
  });
})();
