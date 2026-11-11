/* Reuse the existing rotation layers dialog for concrete imported schedules. */
let importedShiftUsers = [];

function importedUtcInput(value) { return value ? new Date(value).toISOString().slice(0, -1) : ""; }
function importedUtcValue(input, original) {
    const value = input.val() + "Z";
    return original && new Date(value).getTime() === new Date(original).getTime() ? original : value;
}

function addImportedRotationShift(rotation) {
    if (rotation.sync?.editable && canWriteObject(rotation))
        $("#rotation-layer-cards").prepend(importedShiftForm(rotation, null, importedShiftUsers, true));
}

function loadImportedRotationShifts(rotation, after) {
    const container = $("#rotation-layer-cards");
    const editable = rotation.sync?.editable && canWriteObject(rotation);
    if (!after) {
        container.empty();
        importedShiftUsers = [];
        $("#add-layer-card").toggle(Boolean(editable)).prop("disabled", true).text(i18n.t("ds.add_shift"));
    }
    apiGet("/api/rotations/" + rotation.id + "/imported-shifts" + (after ? "?after=" + after : ""), data => {
        if (selectedRotationForLayers !== rotation.id) return;
        importedShiftUsers = data.users;
        $("#add-layer-card").prop("disabled", !data.users.length);
        container.find("[data-import-more]").remove();
        data.items.forEach(shift => container.append(importedShiftForm(rotation, shift, data.users, editable)));
        if (data.next_cursor) container.append($("<button>", {type: "button", class: "btn", "data-import-more": "1", text: i18n.t("ds.more")})
            .on("click", () => loadImportedRotationShifts(rotation, data.next_cursor)));
    });
}

function importedShiftForm(rotation, shift, users, editable) {
    const form = $("<form>").addClass("card form-body form-stack");
    const grid = $("<div>").addClass("form-grid-2").appendTo(form);
    const field = (label, input) => grid.append($("<label>").addClass("form-group").text(label).append(input));
    const user = $("<select>").addClass("input").prop("disabled", !editable);
    users.forEach(item => user.append($("<option>", {value: item.id, text: item.name})));
    if (shift) user.val(shift.user_id);
    const start = $("<input>", {type: "datetime-local", step: "any", required: true, class: "input"}).val(importedUtcInput(shift?.start)).prop("disabled", !editable);
    const end = $("<input>", {type: "datetime-local", step: "any", required: true, class: "input"}).val(importedUtcInput(shift?.end)).prop("disabled", !editable);
    const title = $("<input>", {class: "input", maxlength: 255}).val(shift?.title || "").prop("disabled", !editable);
    field(i18n.t("ds.person"), user);
    field(i18n.t("ds.name"), title);
    field(i18n.t("ds.shift_start"), start);
    field(i18n.t("ds.shift_end"), end);
    const unavailable = $("<input>", {type: "checkbox"}).prop("checked", shift?.unavailable || false).prop("disabled", !editable);
    form.append($("<label>").addClass("checkbox-label").append(unavailable).append($("<span>").text(i18n.t("ds.unavailable"))));
    const replacements = $("<div>").addClass("form-stack").appendTo(form);
    replacements.append($("<strong>").text(i18n.t("ds.replacements")));
    (shift?.replacements || []).forEach(item => replacements.append(importedReplacementRow(item, users, editable)));
    if (editable) {
        form.append($("<div>").addClass("form-actions-inline").append($("<button>", {type: "button", class: "btn", text: i18n.t("ds.add_replacement")})
            .on("click", () => replacements.append(importedReplacementRow(null, users, true)))));
        const actions = $("<div>").addClass("form-actions-inline").appendTo(form);
        actions.append($("<button>", {type: "submit", class: "btn btn-primary", text: i18n.t("ds.save_shift")}));
        if (shift) actions.append($("<button>", {type: "button", class: "btn", text: i18n.t("ds.remove_shift")}).on("click", () => {
            apiDelete("/api/rotations/imported-shifts/" + shift.id, () => loadImportedRotationShifts(rotation));
        }));
    }
    form.on("submit", event => {
        event.preventDefault();
        const rows = replacements.children("[data-import-replacement]").map(function () { return $(this).data("readReplacement")(); }).get();
        apiRequest(shift ? "PUT" : "POST", shift ? "/api/rotations/imported-shifts/" + shift.id : "/api/rotations/" + rotation.id + "/imported-shifts",
            {user_id: Number(user.val()), start: importedUtcValue(start, shift?.start), end: importedUtcValue(end, shift?.end), title: title.val(), unavailable: unavailable.prop("checked"), replacements: rows},
            () => loadImportedRotationShifts(rotation));
    });
    return form;
}

function importedReplacementRow(item, users, editable) {
    const row = $("<div>", {"data-import-replacement": "1"}).addClass("card form-body form-stack");
    const grid = $("<div>").addClass("form-grid-2").appendTo(row);
    const field = (label, input) => grid.append($("<label>").addClass("form-group").text(i18n.t("ds." + label)).append(input));
    const user = $("<select>").addClass("input").prop("disabled", !editable);
    users.forEach(person => user.append($("<option>", {value: person.id, text: person.name})));
    if (item) user.val(item.user_id);
    const start = $("<input>", {type: "datetime-local", step: "any", required: true, class: "input"}).val(importedUtcInput(item?.start)).prop("disabled", !editable);
    const end = $("<input>", {type: "datetime-local", step: "any", required: true, class: "input"}).val(importedUtcInput(item?.end)).prop("disabled", !editable);
    const priority = $("<input>", {type: "text", inputmode: "numeric", pattern: "-?[0-9]+", required: true, class: "input"}).val(item?.precedence ?? "0").prop("disabled", !editable);
    field("person", user);
    field("precedence", priority);
    field("shift_start", start);
    field("shift_end", end);
    const inactive = $("<input>", {type: "checkbox"}).prop("checked", item?.inactive || false).prop("disabled", !editable);
    row.append($("<label>").addClass("checkbox-label").append(inactive).append($("<span>").text(i18n.t("ds.unavailable"))));
    if (editable) row.append($("<div>").addClass("form-actions-inline").append($("<button>", {type: "button", class: "btn", text: i18n.t("ds.remove_replacement")}).on("click", () => row.remove())));
    const id = item?.id || "local:" + Date.now() + ":" + Math.random().toString(36).slice(2);
    row.data("readReplacement", () => ({id, user_id: Number(user.val()), precedence: priority.val(),
        start: importedUtcValue(start, item?.start), end: importedUtcValue(end, item?.end), inactive: inactive.prop("checked")}));
    return row;
}
