/* Manual decisions belong to the loaded Change and never survive SPA navigation. */
let changeReviewVersion = 0;
let changeReviewEditor = null;
let changeReviewPages = { correlations: 1, incidents: 1 };
const changeRelationRequests = { correlations: 0, incidents: 0 };

function changeReviewConflictMessage(xhr) {
    const reason = xhr.responseJSON && xhr.responseJSON.reason;
    const reasons = [
        "relation_exists", "relation_changed", "suggestion_stale", "evidence_changed",
        "incident_role_conflict", "incident_link_removed", "incident_link_changed",
        "incident_link_missing", "incident_changed",
    ];
    return changesText(reasons.includes(reason) ? "review_conflict_" + reason : "review_conflict", {
        reload: i18n.t("common.reload"),
        manual: changesText("manual_relation"),
        edit: changesText("edit_relation"),
        restore: changesText("restore_link"),
        incidents: changesText("incident_relations"),
        episodes: changesText("episode_relations"),
        link: changesText("add_incident"),
    });
}

function closeChangeReview() {
    changeReviewVersion += 1;
    const picker = document.getElementById("change-review-target")?.tomselect;
    if (picker) picker.destroy();
    changeReviewEditor = null;
    setAppModalSaving("#change-review-modal", false);
    closeAppModal("#change-review-modal");
    $("#change-review-note").val("");
    $("#change-review-target").empty();
    $("#change-review-subject, #change-review-error").text("");
}
function clearChangeReviews() {
    closeChangeReview();
    changeReviewPages = { correlations: 1, incidents: 1 };
    changeRelationRequests.correlations += 1;
    changeRelationRequests.incidents += 1;
    $("#changes-correlations, #changes-incident-links").empty();
}
function changeEpisodeLabel(episode) {
    return episode.title + " · " + changesText("episode_number", { number: episode.ordinal })
        + " · " + (episode.started_at ? formatDateTimeMinutes(episode.started_at) : changesText("unknown"))
        + " · " + changesText(episode.state);
}
function loadChangeReviews(requestId) {
    loadChangeRelations("correlations", requestId);
    loadChangeRelations("incidents", requestId);
}
function loadChangeRelations(kind, requestId) {
    const generation = ++changeRelationRequests[kind];
    const page = changeReviewPages[kind];
    const target = kind === "correlations" ? "#changes-correlations" : "#changes-incident-links";
    const prefix = kind === "correlations" ? "#changes-correlations" : "#changes-incident-links";
    const suffix = kind === "incidents" ? "&include_removed=true" : "";
    apiGet("/api/changes/" + changesUid + "/" + kind + "?page=" + page + suffix, function (response) {
        if (!changesActive(requestId) || changeReviewPages[kind] !== page || generation !== changeRelationRequests[kind]) return;
        const rows = $(target).empty();
        response.items.forEach(function (item) {
            const actions = [];
            if (kind === "correlations" && item.can_review) {
                if (item.suggestion_current || item.review_status !== "suggested") {
                    actions.push({label: changesText("confirm"), icon: "fas fa-check", onClick: () => openChangeReview("confirm", item)});
                    actions.push({label: changesText("reject"), icon: "fas fa-times", onClick: () => openChangeReview("reject", item)});
                }
                actions.push({label: changesText("manual_relation"), icon: "fas fa-link", onClick: () => openChangeReview("manual", item)});
            }
            if (kind === "incidents" && item.can_manage) {
                if (item.removed_at) {
                    actions.push({label: changesText("restore_link"), icon: "fas fa-undo", onClick: () => openChangeReview("restore", item)});
                } else {
                    actions.push({label: changesText("edit_relation"), icon: "fas fa-edit", onClick: () => openChangeReview("edit", item)});
                    actions.push({label: changesText("remove_link"), icon: "fas fa-unlink", onClick: () => openChangeReview("remove", item)});
                }
            }
            const label = kind === "correlations" ? changeEpisodeLabel(item.episode) : item.incident.title;
            const status = kind === "correlations"
                ? (item.review_status === "suggested" && !item.suggestion_current ? "stale_suggestion" : item.review_status)
                : (item.removed_at ? "removed_link" : "active_link");
            const cell = $("<td>").text(label);
            if (item.suggestion_current) {
                cell.append($("<small>").addClass("changes-row-context muted").text(changesText("relevance", {score: item.score})));
            }
            if (item.review_evidence && item.review_evidence.note) {
                cell.append($("<small>").addClass("changes-row-context muted").text(item.review_evidence.note));
            }
            rows.append($("<tr>").attr("data-relation-id", item.id).append(
                cell, changesBadgeCell(item.relation_type), changesBadgeCell(status),
                $("<td>").addClass("actions-cell").append(actions.length ? makeActionMenu({object: item, items: actions}) : "—"),
            ));
        });
        if (!response.items.length) changesEmpty(target, 4);
        changesPagination(prefix, response.pagination, kind === "correlations" ? "episode_relations" : "incident_relations");
    }, function (xhr) {
        if (page === changeReviewPages[kind] && generation === changeRelationRequests[kind]) changesFailure(xhr, requestId);
    });
}
function openChangeReview(action, item, context) {
    closeChangeReview();
    const version = changeReviewVersion;
    const requestId = changesRequest;
    changeReviewEditor = {action, item, uid: changesUid, busy: false,
        isCurrent: () => changesActive(requestId),
        onSaved: () => loadChangeReviews(requestId),
        onDenied: (xhr) => changesFailure(xhr, requestId),
        ...context};
    $("#change-review-form")[0].reset();
    $("#change-review-form :input").prop("disabled", false);
    const creating = ["episode", "incident", "episode_change", "incident_change"].includes(action);
    $("#change-review-target-fields").prop("hidden", !creating);
    $("#change-review-target").prop("required", creating);
    $("#change-review-role-field").prop("hidden", action === "remove");
    $("#change-review-title").text(changesText({
        episode: "add_episode", incident: "add_incident", confirm: "confirm", reject: "reject",
        manual: "manual_relation", edit: "edit_relation", remove: "remove_link", restore: "restore_link",
        episode_change: "link_change", incident_change: "link_change",
    }[action]));
    $("#change-review-subject").text(changeReviewEditor.subject || (item ? (item.episode ? changeEpisodeLabel(item.episode) : item.incident.title) : ""));
    const role = action === "confirm" && item.relation_type === "potential_cause" ? "confirmed_cause"
        : action === "manual" ? "context" : item ? item.relation_type : "context";
    $("#change-review-role").val(role);
    $("#change-review-save").prop("disabled", creating);
    openAppModal("#change-review-modal");
    if (creating) initChangeReviewTargetPicker(version).focus();
    else $("#change-review-note").trigger("focus");
}
function changeReviewCurrent(version) {
    return version === changeReviewVersion && changeReviewEditor && changeReviewEditor.isCurrent()
        && $("#change-review-modal").hasClass("is-open");
}
function initChangeReviewTargetPicker(version) {
    const editor = changeReviewEditor;
    const episode = editor.action === "episode";
    const pickingChange = editor.action.endsWith("_change");
    const endpoint = pickingChange ? "/api/changes" : episode ? "/api/changes/" + editor.uid + "/correlation-targets" : "/api/incidents";
    let pending = null;
    function searchUrl(query, page) {
        return endpoint + "?" + new URLSearchParams({search: query.trim(), page: String(page), page_size: "25"});
    }
    $("#change-review-target-label").text(changesText(pickingChange ? "change" : episode ? "episode" : "incident"));
    $("#change-review-target-hint").text(changesText(pickingChange ? "change_picker_hint" : episode ? "episode_picker_hint" : "incident_picker_hint"));
    return new TomSelect("#change-review-target", {
        plugins: ["virtual_scroll"],
        create: false,
        maxItems: 1,
        maxOptions: null,
        valueField: "id",
        labelField: "label",
        searchField: [], // Only the latest server search supplies options.
        preload: "focus",
        loadThrottle: 250,
        placeholder: changesText("find_target"),
        firstUrl: (query) => searchUrl(query, 1),
        onType: function () {
            // Settle the old plugin callback before starting a new search.
            // Late responses then cannot clear or replace the new result set.
            if (pending) {
                const callback = pending.callback;
                pending = null;
                callback([]);
            }
            this.clearOptions();
            this.clearPagination();
            this.loadedSearches = {};
            $("#change-review-error").text("");
        },
        render: {
            option: function (item, escape) {
                return '<div>' + escape(item.label)
                    + (item.disabled ? '<small>' + escape(changesText("picker_denied")) + '</small>' : '') + '</div>';
            },
            no_results: (_, escape) => '<div class="no-results">' + escape(changesText("empty")) + '</div>',
            loading_more: (_, escape) => '<div class="loading-more-results">' + escape(changesText("loading")) + '</div>',
            no_more_results: () => '<div class="no-more-results" hidden></div>',
        },
        load: function (query, callback) {
            if (!changeReviewCurrent(version)) { callback([]); return; }
            const picker = this;
            const url = picker.getUrl(query);
            if (!url) { callback([]); return; }
            const request = {callback};
            pending = request;
            apiGet(url, function (response) {
                if (!changeReviewCurrent(version) || pending !== request) return;
                pending = null;
                const paging = response.pagination;
                picker.setNextUrl(query, paging.page < paging.pages ? searchUrl(query, paging.page + 1) : false);
                callback(response.items.map(function (item) {
                    const allowed = pickingChange || (episode ? item.can_review : item.permissions && item.permissions.can_respond);
                    return {
                        id: pickingChange ? item.uid : item.id,
                        label: pickingChange ? (item.projection === "safe" ? changesText("related") : item.title)
                            + " · " + changesText(item.kind) + " · " + formatDateTimeMinutes(item.occurred_at)
                            : episode ? changeEpisodeLabel(item) : "#" + item.id + " · " + item.title,
                        disabled: !allowed,
                    };
                }));
            }, function (xhr) {
                if (!changeReviewCurrent(version) || pending !== request) return;
                pending = null;
                picker.setNextUrl(query, false);
                callback([]);
                $("#change-review-error").text(changesText("load_error"));
                if (xhr.status === 403 || xhr.status === 404) editor.onDenied(xhr);
            });
        },
    });
}
$(document).on("click", "#changes-add-episode, #changes-add-incident", function () {
    openChangeReview(this.id.endsWith("episode") ? "episode" : "incident", null);
});
$(document).on("change", "#change-review-target", function () {
    $("#change-review-save").prop("disabled", !this.value);
});
$(document).on("click", "#change-review-close, #change-review-cancel", closeChangeReview);
$(document).on("click", "#change-review-modal", function (event) {
    if (event.target === this && !changeReviewEditor?.busy) closeChangeReview();
});
$(document).on("submit", "#change-review-form", function (event) {
    event.preventDefault();
    const editor = changeReviewEditor;
    if (!editor || editor.busy) return;
    const version = changeReviewVersion;
    const item = editor.item;
    const payload = {note: $("#change-review-note").val().trim(), relation_type: $("#change-review-role").val()};
    let method = "POST";
    let url;
    if (editor.action === "episode" || editor.action === "episode_change") {
        url = "/api/changes/" + (editor.action === "episode_change" ? $("#change-review-target").val() : editor.uid) + "/correlations";
        payload.episode_id = editor.action === "episode_change" ? editor.targetId : Number($("#change-review-target").val());
    } else if (["confirm", "reject", "manual"].includes(editor.action)) {
        url = "/api/changes/" + editor.uid + "/correlations/" + item.id + "/review";
        payload.row_version = item.row_version;
        payload.decision = editor.action === "reject" ? "rejected" : "confirmed";
        payload.evidence_version = item.evidence_version;
        payload.manual = editor.action === "manual";
    } else {
        const incidentId = editor.action === "incident_change" ? editor.targetId : item ? item.incident.id : Number($("#change-review-target").val());
        url = "/api/incidents/" + incidentId + "/changes";
        if (["incident", "restore", "incident_change"].includes(editor.action)) {
            payload.change_uid = editor.action === "incident_change" ? $("#change-review-target").val() : editor.uid;
            if (item) payload.row_version = item.row_version;
        } else {
            url += "/" + item.id;
            payload.row_version = item.row_version;
            method = editor.action === "remove" ? "DELETE" : "PATCH";
            if (method === "DELETE") delete payload.relation_type;
        }
    }
    editor.busy = true;
    const picker = document.getElementById("change-review-target")?.tomselect;
    if (picker) picker.disable();
    $("#change-review-form :input").prop("disabled", true);
    $("#change-review-error").text("");
    setAppModalSaving("#change-review-modal", true);
    apiRequest(method, url, payload, function () {
        if (!changeReviewCurrent(version)) return;
        closeChangeReview();
        editor.onSaved();
    }, function (xhr) {
        if (!changeReviewCurrent(version)) return;
        editor.busy = false;
        setAppModalSaving("#change-review-modal", false);
        $("#change-review-form :input").prop("disabled", false);
        if (picker) picker.enable();
        $("#change-review-error").text(xhr.status === 409 ? changeReviewConflictMessage(xhr) : changesText("save_error"));
        document.getElementById("change-review-error").scrollIntoView({block: "nearest"});
        if (xhr.status === 409) $("#change-review-save").prop("disabled", true);
        if (xhr.status === 403 || xhr.status === 404) editor.onDenied(xhr);
    });
});
$(document).on("click", "[data-change-relations-page]", function () {
    const kind = this.dataset.changeRelationsPage;
    changeReviewPages[kind] += this.id.endsWith("next") ? 1 : -1;
    loadChangeRelations(kind, changesRequest);
});
