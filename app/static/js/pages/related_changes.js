/* Shared Related Changes tables. Each response belongs to one resource/episode. */
const RelatedChanges = (() => {
    const states = {};

    function clear(kind) {
        const state = states[kind];
        if (!state) return;
        if (changeReviewEditor?.owner === state) closeChangeReview();
        state.root.find("[data-related-episodes]")[0]?.tomselect?.destroy();
        state.root.find("[data-related-episodes]").empty();
        state.root.find("[data-related-episode-selector]").prop("hidden", true);
        state.root.find("tbody").empty();
        state.root.find("[data-related-error], [data-related-count], [data-related-eligibility]").text("");
        state.root.find("[data-related-add]").prop("hidden", true);
        state.root.find("[data-related-paging]").prop("hidden", true);
        delete states[kind];
    }
    function active(state) {
        return states[state.kind] === state && state.isCurrent();
    }
    function fail(state, xhr) {
        if (!active(state)) return;
        state.request += 1;
        state.root.find("[data-related-episodes]")[0]?.tomselect?.destroy();
        state.root.find("[data-related-episodes]").empty();
        state.root.find("[data-related-episode-selector]").prop("hidden", true);
        state.root.find("tbody").empty();
        state.root.find("[data-related-count], [data-related-eligibility]").text("");
        state.root.find("[data-related-add]").prop("hidden", true);
        state.root.find("[data-related-error]").text(changesText(xhr.status === 403 || xhr.status === 404 ? "unavailable" : "load_error"));
        if (changeReviewEditor?.owner === state) closeChangeReview();
    }
    function editorContext(state, item) {
        const episodeId = state.episode?.id;
        return {
            owner: state, uid: item?.change.uid, targetId: state.kind === "alert" ? episodeId : state.id,
            subject: state.kind === "alert" && state.episode ? changeEpisodeLabel(state.episode) : state.title,
            isCurrent: () => active(state) && state.episode?.id === episodeId,
            onSaved: state.onSaved || (() => load(state)),
            onDenied: (xhr) => fail(state, xhr),
        };
    }
    function actions(state, item) {
        const items = [];
        function add(action, label, icon) {
            items.push({label: changesText(label), icon: "fas " + icon,
                onClick: () => openChangeReview(action, item, editorContext(state, item))});
        }
        if (state.kind === "alert" && item.can_review) {
            if (item.suggestion_current || item.review_status !== "suggested") {
                add("confirm", "confirm", "fa-check");
                add("reject", "reject", "fa-times");
            }
            add("manual", "manual_relation", "fa-link");
        } else if (state.kind === "incident" && item.can_manage) {
            if (item.removed_at) add("restore", "restore_link", "fa-undo");
            else {
                add("edit", "edit_relation", "fa-edit");
                add("remove", "remove_link", "fa-unlink");
            }
        }
        return items;
    }
    function render(state, response) {
        const root = state.root;
        const body = root.find("tbody").empty();
        response.items.forEach((item) => {
            const change = item.change;
            const link = $("<a>").attr("href", "/changes/" + change.uid)
                .text(change.projection === "safe" ? changesText("related") : change.title);
            const cell = $("<td>").append($("<div>").addClass("changes-row-heading").append(changesKindIcon(change.kind), link));
            cell.append($("<small>").addClass("changes-row-context muted").text(formatDateTimeMinutes(change.occurred_at)));
            if (item.suggestion_current) cell.append($("<small>").addClass("changes-row-context muted")
                .text(changesText("relevance", {score: item.score})));
            if (item.review_evidence?.note) cell.append($("<small>").addClass("changes-row-context muted").text(item.review_evidence.note));
            const status = state.kind === "incident" ? (item.removed_at ? "removed_link" : "active_link")
                : item.review_status === "suggested" && !item.suggestion_current ? "stale_suggestion" : item.review_status;
            const menu = actions(state, item);
            body.append($("<tr>").attr("data-relation-id", item.id).append(cell,
                changesBadgeCell(item.relation_type), changesBadgeCell(status),
                $("<td>").addClass("actions-cell").append(menu.length ? makeActionMenu({object: item, items: menu}) : "—")));
        });
        if (!response.items.length) changesEmpty(body, 4);
        const paging = response.pagination;
        root.find("[data-related-count]").text(changesText(paging.pages > 1 ? "section_pagination" : "section_count", {
            section: changesText("related_changes"), page: paging.page, pages: Math.max(1, paging.pages), count: paging.total,
        }));
        root.find("[data-related-paging]").prop("hidden", paging.pages <= 1);
        root.find("[data-related-prev]").prop("disabled", paging.page <= 1);
        root.find("[data-related-next]").prop("disabled", paging.page >= paging.pages);
        root.find("[data-related-add]").prop("hidden", !(state.kind === "alert" ? response.can_review && response.episode : state.canManage));
    }
    function load(state) {
        if (!active(state)) return;
        const generation = ++state.request;
        state.root.find("[data-related-error]").text("");
        state.root.find("tbody").empty();
        state.root.find("[data-related-add]").prop("hidden", true);
        state.root.find("[data-related-count]").text(changesText("loading"));
        state.root.find("[data-related-prev], [data-related-next]").prop("disabled", true);
        const params = new URLSearchParams({page: state.page, page_size: 25});
        if (state.kind === "incident") params.set("include_removed", "true");
        else if (state.episode) params.set("episode_id", state.episode.id);
        const url = state.kind === "incident" ? "/api/incidents/" + state.id + "/changes"
            : "/api/alert-groups/" + state.id + "/related-changes";
        apiGet(url + "?" + params, (response) => {
            if (!active(state) || generation !== state.request) return;
            if (state.kind === "alert") {
                state.episode = response.episode;
                state.root.find("[data-related-episode-selector]").prop("hidden", !response.episode);
                state.root.find("[data-related-eligibility]").text(changesText("eligibility_" + response.eligibility));
                if (response.episode && !state.root.find("[data-related-episodes]")[0].tomselect) initEpisodes(state);
            }
            render(state, response);
        }, (xhr) => { if (generation === state.request) fail(state, xhr); });
    }
    function initEpisodes(state) {
        const select = state.root.find("[data-related-episodes]")[0];
        const picker = new TomSelect(select, {
            plugins: ["virtual_scroll"], create: false, maxItems: 1, maxOptions: null,
            valueField: "id", labelField: "label", searchField: [], controlInput: null,
            options: [{id: state.episode.id, label: changeEpisodeLabel(state.episode), episode: state.episode}],
            items: [state.episode.id], preload: "focus",
            firstUrl: () => "/api/alert-groups/" + state.id + "/episodes?page_size=25&page=1",
            load: function (query, callback) {
                const url = this.getUrl(query);
                if (!url || !active(state)) { callback([]); return; }
                const control = this;
                apiGet(url, (response) => {
                    if (!active(state) || select.tomselect !== control) return;
                    const page = response.pagination;
                    control.setNextUrl(query, page.page < page.pages ? url.replace(/page=\d+$/, "page=" + (page.page + 1)) : false);
                    callback(response.items.map((episode) => ({id: episode.id, label: changeEpisodeLabel(episode), episode})));
                }, (xhr) => { if (active(state) && select.tomselect === control) { callback([]); fail(state, xhr); } });
            },
            onChange: function (id) {
                if (!active(state) || !id || Number(id) === state.episode?.id) return;
                if (changeReviewEditor?.owner === state) closeChangeReview();
                state.episode = this.options[id].episode;
                state.page = 1;
                load(state);
            },
        });
        picker.wrapper.setAttribute("aria-label", changesText("episode"));
    }
    function mount(kind, id, options) {
        clear(kind);
        const state = {kind, id, root: $("#" + kind + "-related-changes"), page: 1, request: 0, ...options};
        states[kind] = state;
        state.root.find("[data-related-reload]").off("click.related").on("click.related", () => load(state));
        state.root.find("[data-related-prev], [data-related-next]").off("click.related").on("click.related", function () {
            state.page += this.hasAttribute("data-related-next") ? 1 : -1;
            load(state);
        });
        state.root.find("[data-related-add]").off("click.related").on("click.related", () => {
            openChangeReview(kind === "alert" ? "episode_change" : "incident_change", null, editorContext(state));
        });
        load(state);
    }
    return {clear, mount};
})();
