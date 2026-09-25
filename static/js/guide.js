// Guide de premiere visite (invites et agent du livre d'or) : s'ouvre une seule fois, se ferme d'un
// toucher, et ne peut jamais empecher d'utiliser la page. Sans JavaScript, il reste simplement cache.
(function () {
  const guide = document.getElementById("guide");
  if (!guide) {
    return;
  }

  const slides = Array.from(guide.querySelectorAll("[data-guide-slide]"));
  const dots = Array.from(guide.querySelectorAll(".guide__dots i"));
  const nextButton = guide.querySelector("[data-guide-next]");
  const storageKey = "memora_guide_" + (guide.dataset.guideKey || "default");
  const nextLabel = nextButton ? nextButton.textContent : "Suivant";
  const doneLabel = guide.dataset.doneLabel || "Compris";
  let index = 0;
  let opener = null;

  function remember() {
    try {
      window.localStorage.setItem(storageKey, "1");
    } catch {
      // Navigation privee : le guide reviendra a la prochaine visite, sans gravite.
    }
  }

  function alreadySeen() {
    try {
      return window.localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  }

  function show(position) {
    index = Math.max(0, Math.min(position, slides.length - 1));
    slides.forEach(function (slide, i) {
      slide.hidden = i !== index;
    });
    dots.forEach(function (dot, i) {
      dot.classList.toggle("is-active", i === index);
    });
    if (nextButton) {
      nextButton.textContent = index === slides.length - 1 ? doneLabel : nextLabel;
    }
  }

  function open(trigger) {
    if (!slides.length) {
      return;
    }
    opener = trigger || null;
    show(0);
    guide.hidden = false;
    document.body.classList.add("guide-open");
    if (nextButton) {
      nextButton.focus({ preventScroll: true });
    }
  }

  function close() {
    guide.hidden = true;
    document.body.classList.remove("guide-open");
    remember();
    if (opener && typeof opener.focus === "function") {
      opener.focus({ preventScroll: true });
    }
  }

  if (nextButton) {
    nextButton.addEventListener("click", function () {
      if (index >= slides.length - 1) {
        close();
      } else {
        show(index + 1);
      }
    });
  }
  guide.querySelectorAll("[data-guide-close]").forEach(function (element) {
    element.addEventListener("click", close);
  });
  document.addEventListener("keydown", function (event) {
    if (!guide.hidden && event.key === "Escape") {
      close();
    }
  });
  document.querySelectorAll("[data-guide-open]").forEach(function (trigger) {
    trigger.addEventListener("click", function () {
      open(trigger);
    });
  });

  // Premiere visite seulement, et jamais par-dessus une camera deja ouverte.
  if (!alreadySeen() && !document.body.classList.contains("camera-open")) {
    window.setTimeout(function () {
      if (!document.body.classList.contains("camera-open")) {
        open(null);
      }
    }, 450);
  }
})();
