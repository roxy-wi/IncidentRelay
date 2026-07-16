let appModalZIndex = 1000;

function getNextAppOverlayZIndex() {
  appModalZIndex += 10;
  return appModalZIndex;
}

function resetAppOverlayZIndexIfIdle() {
  if (!$(".app-modal.is-open, .modal.is-open, .app-dialog.is-open").length) {
    appModalZIndex = 1000;
  }
}

function resetAppDialog() {
    /*
     * Reset global dialog state before showing a new message.
     */
    $("#app-dialog-modal")
        .removeClass("app-dialog-error app-dialog-warning app-dialog-success app-dialog-info");

    $("#app-dialog-title").text(i18n.t("shared.dialog.message"));
    $("#app-dialog-subtitle").text("");
    $("#app-dialog-message").text("");
    $("#app-dialog-icon").text("!");

    $("#app-dialog-cancel").show().text(i18n.t("shared.dialog.cancel"));
    $("#app-dialog-confirm")
        .removeClass("btn-danger btn-warning btn-success btn-primary")
        .addClass("btn-primary")
        .text(i18n.t("shared.dialog.ok"));
}

function showAppDialog(options) {
    /*
     * Show global application dialog.
     *
     * Returns:
     *   jQuery Promise resolved on confirm, rejected on cancel/close.
     */
    const deferred = $.Deferred();
    const opts = options || {};
    const type = opts.type || "info";
    const dialog = $("#app-dialog-modal");

    resetAppDialog();

    dialog.addClass("app-dialog-" + type);
    openAppModal(dialog);

    $("#app-dialog-title").text(opts.title || i18n.t("shared.dialog.message"));
    $("#app-dialog-subtitle").text(opts.subtitle || "");
    $("#app-dialog-message").text(opts.message || "");

    $("#app-dialog-icon").text(opts.icon || getAppDialogIcon(type));

    $("#app-dialog-confirm")
        .text(opts.confirmText || i18n.t("shared.dialog.ok"))
        .removeClass("btn-primary btn-danger btn-warning btn-success")
        .addClass(opts.confirmClass || getAppDialogButtonClass(type));

    if (opts.cancelText === null || opts.hideCancel) {
        $("#app-dialog-cancel").hide();
    } else {
        $("#app-dialog-cancel").show().text(opts.cancelText || i18n.t("shared.dialog.cancel"));
    }

    $("#app-dialog-confirm").off("click.appDialog").on("click.appDialog", function () {
        closeAppModal("#app-dialog-modal");
        deferred.resolve();
    });

    $("#app-dialog-cancel, #app-dialog-close")
        .off("click.appDialog")
        .on("click.appDialog", function () {
            closeAppModal("#app-dialog-modal");
            deferred.reject();
        });

    return deferred.promise();
}


function getAppDialogIcon(type) {
    /*
     * Return icon text for dialog type.
     */
    if (type === "error") {
        return "!";
    }

    if (type === "warning") {
        return "!";
    }

    if (type === "success") {
        return "✓";
    }

    return "i";
}


function getAppDialogButtonClass(type) {
    /*
     * Return default button class for dialog type.
     */
    if (type === "error") {
        return "btn-danger";
    }

    if (type === "warning") {
        return "btn-warning";
    }

    if (type === "success") {
        return "btn-success";
    }

    return "btn-primary";
}


function showAppSuccess(message, title) {
    /*
     * Show success dialog.
     */
    return showAppDialog({
        type: "success",
        title: title || i18n.t("shared.dialog.success"),
        message: message || i18n.t("shared.dialog.done"),
        confirmText: i18n.t("shared.dialog.ok"),
        hideCancel: true
    });
}


function showAppConfirm(options) {
    /*
     * Show confirmation dialog.
     */
    return showAppDialog({
        type: options.type || "warning",
        title: options.title || i18n.t("shared.dialog.confirm_action"),
        subtitle: options.subtitle || "",
        message: options.message || i18n.t("shared.dialog.are_you_sure"),
        confirmText: options.confirmText || i18n.t("shared.dialog.confirm"),
        cancelText: options.cancelText || i18n.t("shared.dialog.cancel"),
        confirmClass: options.confirmClass || "btn-warning"
    });
}
$(document).on("click", "#app-dialog-modal", function (event) {
    /*
     * Close dialog when clicking outside the modal dialog.
     */
    if (event.target !== this) {
        return;
    }

    if ($(this).hasClass("is-hidden")) {
        return;
    }

    event.stopImmediatePropagation();
    $("#app-dialog-cancel").trigger("click");
});

$(document).on("keydown", function (event) {
    /*
     * Close global dialog by Escape.
     */
    if (event.key !== "Escape") {
        return;
    }

    const dialog = $("#app-dialog-modal");

    if (!dialog.length || dialog.hasClass("is-hidden")) {
        return;
    }

    event.stopImmediatePropagation();
    $("#app-dialog-cancel").trigger("click");
});
function formatJsonTextarea(selector, fallbackValue, label) {
    const $field = $(selector);
    const raw = String($field.val() || "").trim();

    let parsed;

    try {
        parsed = raw ? JSON.parse(raw) : fallbackValue;
    } catch (error) {
        showAppError(
            i18n.t("shared.json.invalid_field", {label: label, error: error.message}),
            i18n.t("shared.json.invalid_title")
        );
        return false;
    }

    $field.val(JSON.stringify(parsed, null, 2));
    return true;
}
function getAppModal(selectorOrElement) {
    /*
     * Return jQuery modal object from selector, DOM element, jQuery object or event.
     */
    if (!selectorOrElement) {
        return $();
    }

    if (selectorOrElement.jquery) {
        return selectorOrElement;
    }

    if (selectorOrElement.currentTarget) {
        return $(selectorOrElement.currentTarget).closest(".app-modal, .modal");
    }

    return $(selectorOrElement);
}

function closeAppModal(selectorOrElement) {
    const modal = getAppModal(selectorOrElement);

    if (!modal.length) {
        return modal;
    }

    modal
        .removeClass("is-open")
        .addClass("is-hidden")
        .css({
            display: "none",
            zIndex: "",
        })
        .attr("aria-hidden", "true");

    if (!hasOpenAppModals()) {
        $("body").removeClass("modal-open");
    }

    resetAppOverlayZIndexIfIdle();

    return modal;
}

function hasOpenAppModals() {
    return $(".app-modal.is-open, .modal.is-open").length > 0;
}

function openAppModal(selectorOrElement) {
    const modal = getAppModal(selectorOrElement);

    if (!modal.length) {
        return modal;
    }

    modal
        .removeClass("is-hidden")
        .addClass("is-open")
        .css({
            display: "flex",
            zIndex: getNextAppOverlayZIndex(),
        })
        .attr("aria-hidden", "false");

    $("body").addClass("modal-open");

    return modal;
}

function closeTopAppModal() {
    /*
     * Close latest opened modal.
     */
    const modal = $(".app-modal.is-open, .modal.is-open").last();

    if (!modal.length) {
        return;
    }

    closeAppModal(modal);
}
$(document).on("click", "[data-modal-close]", function () {
    const target = $(this).data("modal-close");

    if (target) {
        closeAppModal(target);
        return;
    }

    closeAppModal($(this).closest(".app-modal, .modal"));
});

$(document).on("click", ".app-modal, .modal", function (event) {
    if (event.target === this) {
        closeAppModal(this);
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape") {
        closeTopAppModal();
    }
});
