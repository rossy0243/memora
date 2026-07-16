(function () {
  const form = document.querySelector("[data-event-form]");
  if (!form) {
    return;
  }

  const eventTypeSelect = form.querySelector("[data-event-type-select]");
  const customTypeField = form.querySelector("[data-custom-event-type-field]");
  const customTypeInput = form.querySelector("[data-custom-event-type]");

  function syncCustomTypeField() {
    if (!eventTypeSelect || !customTypeField || !customTypeInput) {
      return;
    }
    const otherTypeId = eventTypeSelect.dataset.otherEventTypeId;
    const shouldShow = otherTypeId && eventTypeSelect.value === otherTypeId;
    customTypeField.hidden = !shouldShow;
    customTypeInput.required = shouldShow;
    if (!shouldShow) {
      customTypeInput.value = "";
    }
  }

  if (eventTypeSelect) {
    eventTypeSelect.addEventListener("change", syncCustomTypeField);
  }
  syncCustomTypeField();

  const momentSelect = form.querySelector("[data-moment-select]");
  if (!momentSelect) {
    return;
  }

  const suggestionsNode = document.getElementById("moment-suggestions-data");
  const suggestionsByEventType = suggestionsNode ? JSON.parse(suggestionsNode.textContent || "{}") : {};
  let touched = Array.from(momentSelect.selectedOptions).length > 0;

  const picker = document.createElement("div");
  picker.className = "moment-picker";
  picker.innerHTML = [
    '<div class="moment-picker__control" role="combobox" aria-expanded="false" aria-haspopup="listbox">',
    '<div class="moment-picker__chips" aria-live="polite"></div>',
    '<input class="moment-picker__search" type="text" autocomplete="off" placeholder="Rechercher ou ajouter un moment">',
    "</div>",
    '<div class="moment-picker__menu" role="listbox" hidden></div>',
  ].join("");
  momentSelect.after(picker);
  momentSelect.classList.add("is-enhanced");

  const control = picker.querySelector(".moment-picker__control");
  const chips = picker.querySelector(".moment-picker__chips");
  const input = picker.querySelector(".moment-picker__search");
  const menu = picker.querySelector(".moment-picker__menu");
  let isOpen = false;

  function optionLabel(option) {
    return (option.textContent || "").trim();
  }

  function selectedValues() {
    return new Set(Array.from(momentSelect.selectedOptions).map((option) => option.value));
  }

  function allOptions() {
    return Array.from(momentSelect.options);
  }

  function normalizedQuery() {
    return input.value.trim().replace(/\s+/g, " ");
  }

  function exactOptionFor(label) {
    const normalizedLabel = label.toLowerCase();
    return allOptions().find((option) => optionLabel(option).toLowerCase() === normalizedLabel);
  }

  function syncOption(value, label, selected) {
    let option = allOptions().find((candidate) => candidate.value === value);
    if (!option) {
      option = new Option(label, value, false, false);
      momentSelect.appendChild(option);
    }
    option.selected = selected;
  }

  function addCustomMoment() {
    const label = normalizedQuery();
    if (!label) {
      return;
    }
    const existing = exactOptionFor(label);
    if (existing) {
      existing.selected = true;
    } else {
      syncOption(`new:${label}`, label, true);
    }
    touched = true;
    input.value = "";
    openMenu();
    render();
  }

  function removeValue(value) {
    const option = allOptions().find((candidate) => candidate.value === value);
    if (option) {
      option.selected = false;
    }
    touched = true;
    render();
  }

  function selectValue(value) {
    const option = allOptions().find((candidate) => candidate.value === value);
    if (!option) {
      return;
    }
    option.selected = true;
    touched = true;
    input.value = "";
    openMenu();
    render();
  }

  function openMenu() {
    isOpen = true;
    menu.hidden = false;
    control.setAttribute("aria-expanded", "true");
  }

  function closeMenu() {
    isOpen = false;
    menu.hidden = true;
    control.setAttribute("aria-expanded", "false");
  }

  function render() {
    const selected = selectedValues();
    chips.innerHTML = "";
    Array.from(momentSelect.selectedOptions).forEach((option) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "moment-picker__chip";
      chip.textContent = optionLabel(option);
      chip.setAttribute("aria-label", `Retirer ${optionLabel(option)}`);
      chip.addEventListener("click", () => removeValue(option.value));
      chips.appendChild(chip);
    });

    input.placeholder = selected.size ? "Ajouter un autre moment" : "Rechercher: discours, cocktail, piste de danse...";

    const query = normalizedQuery();
    const queryLower = query.toLowerCase();
    const availableOptions = allOptions()
      .filter((option) => !selected.has(option.value))
      .filter((option) => !queryLower || optionLabel(option).toLowerCase().includes(queryLower))
      .slice(0, 8);

    menu.innerHTML = "";
    availableOptions.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "moment-picker__option";
      button.textContent = optionLabel(option);
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => selectValue(option.value));
      menu.appendChild(button);
    });

    if (query && !exactOptionFor(query)) {
      const addOption = document.createElement("button");
      addOption.type = "button";
      addOption.className = "moment-picker__option moment-picker__option--add";
      addOption.textContent = `Ajouter "${query}"`;
      addOption.addEventListener("mousedown", (event) => event.preventDefault());
      addOption.addEventListener("click", addCustomMoment);
      menu.prepend(addOption);
    }

    if (!menu.children.length) {
      const empty = document.createElement("div");
      empty.className = "moment-picker__empty";
      empty.textContent = "Aucun moment disponible";
      menu.appendChild(empty);
    }

    if (isOpen) {
      menu.hidden = false;
    }
  }

  function applyEventTypeSuggestions() {
    if (!eventTypeSelect || touched) {
      return;
    }
    const suggestedValues = suggestionsByEventType[eventTypeSelect.value] || [];
    if (!suggestedValues.length) {
      return;
    }
    Array.from(momentSelect.options).forEach((option) => {
      option.selected = suggestedValues.includes(option.value);
    });
    render();
  }

  control.addEventListener("click", () => {
    input.focus();
    openMenu();
    render();
  });
  input.addEventListener("focus", () => {
    openMenu();
    render();
  });
  input.addEventListener("input", () => {
    openMenu();
    render();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCustomMoment();
    } else if (event.key === "Escape") {
      closeMenu();
    } else if (event.key === "Backspace" && !input.value) {
      const selectedOptions = Array.from(momentSelect.selectedOptions);
      const lastOption = selectedOptions[selectedOptions.length - 1];
      if (lastOption) {
        removeValue(lastOption.value);
      }
    }
  });
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target)) {
      closeMenu();
    }
  });
  if (eventTypeSelect) {
    eventTypeSelect.addEventListener("change", applyEventTypeSuggestions);
  }
  applyEventTypeSuggestions();
  render();
  closeMenu();
})();
