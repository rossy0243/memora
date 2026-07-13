(function () {
  const form = document.querySelector("[data-event-form]");
  if (!form) {
    return;
  }

  const eventTypeSelect = form.querySelector("[data-event-type-select]");
  const customTypeField = form.querySelector("[data-custom-event-type-field]");
  const customTypeInput = form.querySelector("[data-custom-event-type]");

  if (!eventTypeSelect || !customTypeField || !customTypeInput) {
    return;
  }

  function syncCustomTypeField() {
    const otherTypeId = eventTypeSelect.dataset.otherEventTypeId;
    const shouldShow = otherTypeId && eventTypeSelect.value === otherTypeId;
    customTypeField.hidden = !shouldShow;
    customTypeInput.required = shouldShow;
    if (!shouldShow) {
      customTypeInput.value = "";
    }
  }

  eventTypeSelect.addEventListener("change", syncCustomTypeField);
  syncCustomTypeField();
})();
