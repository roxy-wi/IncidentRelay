/* Read-only presentation adapter for persisted Event Orchestration executions.
 * Keep the rendering shared with the Simulator: stored results use the same
 * rule/action structures but have a different outer response envelope.
 */

const ORCHESTRATION_EXECUTION_DIFF_LIMIT = 100;
const ORCHESTRATION_EXECUTION_DIFF_NODES = 4000;
const ORCHESTRATION_EXECUTION_DIFF_DEPTH = 14;

function orchestrationExecutionTraceFlatten(value, fields, path, state, depth) {
    if (state.count >= ORCHESTRATION_EXECUTION_DIFF_NODES) {
        state.truncated = true;
        return;
    }

    if (depth < ORCHESTRATION_EXECUTION_DIFF_DEPTH && value !== null && typeof value === "object") {
        const keys = Array.isArray(value)
            ? value.map(function (_, index) { return index; })
            : Object.keys(value).sort();

        if (!keys.length) {
            fields.set(path || "$", value);
            state.count += 1;
            return;
        }

        for (const key of keys) {
            if (state.count >= ORCHESTRATION_EXECUTION_DIFF_NODES) {
                state.truncated = true;
                break;
            }
            const nextPath = Array.isArray(value)
                ? (path || "") + "[" + key + "]"
                : (path ? path + "." + key : key);
            orchestrationExecutionTraceFlatten(value[key], fields, nextPath, state, depth + 1);
        }
        return;
    }

    fields.set(path || "$", value);
    state.count += 1;
}

function orchestrationExecutionTraceDiff(before, after) {
    const left = new Map();
    const right = new Map();
    const leftState = {count: 0, truncated: false};
    const rightState = {count: 0, truncated: false};
    orchestrationExecutionTraceFlatten(before || {}, left, "", leftState, 0);
    orchestrationExecutionTraceFlatten(after || {}, right, "", rightState, 0);

    const paths = Array.from(new Set([...left.keys(), ...right.keys()])).sort();
    const changes = [];
    let totalChanges = 0;

    paths.forEach(function (path) {
        const hasBefore = left.has(path);
        const hasAfter = right.has(path);
        const beforeValue = hasBefore ? left.get(path) : null;
        const afterValue = hasAfter ? right.get(path) : null;
        if (hasBefore === hasAfter && JSON.stringify(beforeValue) === JSON.stringify(afterValue)) {
            return;
        }
        totalChanges += 1;
        if (changes.length < ORCHESTRATION_EXECUTION_DIFF_LIMIT) {
            changes.push({path: path, before: beforeValue, after: afterValue});
        }
    });

    return {
        changed: totalChanges > 0,
        total_changes: totalChanges,
        truncated: totalChanges > changes.length || leftState.truncated || rightState.truncated,
        changes: changes,
    };
}

function orchestrationExecutionTraceSelected(context) {
    const state = context.result || {};
    const routing = state.routing || {};
    const policies = state.policies || {};
    const selectedEntity = function (key, fallback) {
        return routing[key] != null ? {id: routing[key]} : (fallback || null);
    };
    const policyEntity = function (key) {
        return policies[key] != null ? {id: policies[key]} : null;
    };

    return {
        route: selectedEntity("route_id", context.route),
        team: selectedEntity("team_id", context.team),
        service: selectedEntity("service_id", context.service),
        escalation_policy: policyEntity("escalation_policy_id"),
        notification_policy: policyEntity("notification_policy_id"),
        priority_policy: policyEntity("priority_policy_id"),
        grouping: state.grouping || {},
    };
}

function orchestrationExecutionTraceCandidate(context, selected) {
    const state = context.result || {};
    const event = context.event || {};
    const grouping = state.grouping || {};
    const candidateId = function (entity) {
        return entity && entity.id != null ? entity.id : null;
    };
    return {
        route_id: candidateId(selected.route),
        team_id: candidateId(selected.team),
        service_id: candidateId(selected.service),
        severity: event.severity == null ? null : event.severity,
        title: event.title == null ? null : event.title,
        group_key: grouping.group_key || event.group_key || null,
        disposition: state.disposition || "process",
    };
}

function orchestrationExecutionTracePresentation(row, trace) {
    const execution = trace && trace.result && typeof trace.result === "object" ? trace.result : null;
    const context = (execution && execution.context) || {};
    const state = context.result || {};
    const selected = orchestrationExecutionTraceSelected(context);
    const disposition = state.disposition || row.disposition || "process";
    const errors = [];
    if (trace.error) { errors.push(typeof trace.error === "string" ? trace.error : orchestrationJson(trace.error)); }
    if (trace.rejected_reason) { errors.push(typeof trace.rejected_reason === "string" ? trace.rejected_reason : orchestrationJson(trace.rejected_reason)); }

    const result = {
        executed: Boolean(execution && Array.isArray(execution.rules)),
        execution: execution || {},
        final_context: context,
        selected: selected,
        disposition: {
            type: disposition,
            reason: state[disposition + "_reason"] || null,
            pause_seconds: state.pause_seconds,
        },
        version_id: row.version_id,
        duration_ms: row.duration_ms == null ? undefined : row.duration_ms,
        selected_normalizer: row.integration_name || row.source,
        input_output_diff: execution
            ? orchestrationExecutionTraceDiff(trace.initial_context || {}, context)
            : {changed: false, total_changes: 0, changes: []},
        errors: errors,
    };

    // In shadow mode this is candidate vs actual lifecycle result, not an
    // active-vs-draft comparison. Only compare fields present in both shapes.
    if (execution && trace.actual_result && typeof trace.actual_result === "object") {
        const candidate = orchestrationExecutionTraceCandidate(context, selected);
        const actual = trace.actual_result;
        const candidateComparable = {};
        const actualComparable = {};
        Object.keys(candidate).forEach(function (key) {
            if (Object.prototype.hasOwnProperty.call(actual, key)) {
                candidateComparable[key] = candidate[key];
                actualComparable[key] = actual[key];
            }
        });
        if (Object.keys(candidateComparable).length) {
            result.active_draft_diff = orchestrationExecutionTraceDiff(candidateComparable, actualComparable);
        }
    }

    return result;
}

function switchOrchestrationExecutionTraceTab(tab) {
    const selected = ["summary", "rules", "changes", "raw"].indexOf(tab) >= 0 ? tab : "summary";
    $("[data-execution-trace-tab]")
        .removeClass("is-active")
        .attr("aria-selected", "false");
    $("[data-execution-trace-tab='" + selected + "']")
        .addClass("is-active")
        .attr("aria-selected", "true");
    $("[data-execution-trace-panel]").addClass("is-hidden");
    $("[data-execution-trace-panel='" + selected + "']").removeClass("is-hidden");
}

function renderOrchestrationExecutionTraceDetails(row, trace) {
    const data = orchestrationExecutionTracePresentation(row, trace);
    const applied = trace.applied === true;
    const mode = trace.mode || row.mode || "disabled";

    renderOrchestrationSimulationOverview(data, "#orchestration-execution-overview");
    renderOrchestrationSimulationSummary(data, "#orchestration-execution-summary", {recorded: true});
    renderOrchestrationSimulationRules(data, "#orchestration-execution-rules");
    renderOrchestrationSimulationChanges(data, "#orchestration-execution-changes", {
        secondaryTitleKey: "orchestrations.executions.candidate_actual",
    });

    $("#orchestration-execution-metadata").empty().append(
        orchestrationSimulationMetric(
            i18n.t("orchestrations.executions.mode"),
            i18n.t("orchestrations.mode." + mode, {}, mode),
            {badge: true, badgeKind: mode === "active" ? "status-active" : "status-muted"}
        ),
        orchestrationSimulationMetric(
            i18n.t("orchestrations.executions.application"),
            i18n.t(applied ? "orchestrations.executions.applied" : "orchestrations.executions.not_applied"),
            {badge: true, badgeKind: applied ? "status-active" : "status-warning"}
        )
    );

    switchOrchestrationExecutionTraceTab("summary");
}

$(document).on("click", "[data-execution-trace-tab]", function () {
    switchOrchestrationExecutionTraceTab($(this).attr("data-execution-trace-tab"));
});
