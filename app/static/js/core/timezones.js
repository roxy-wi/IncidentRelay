window.AppTimezones = (function () {
    const fallbackTimezones = [
        "UTC",
        "Europe/London",
        "Europe/Berlin",
        "Europe/Paris",
        "Europe/Moscow",
        "Asia/Almaty",
        "Asia/Tashkent",
        "Asia/Dubai",
        "Asia/Yekaterinburg",
        "Asia/Novosibirsk",
        "Asia/Vladivostok",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Asia/Kolkata",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Sao_Paulo",
        "Australia/Sydney",
    ];

    function getBrowserTimezones() {
        let zones = [];

        if (window.Intl && typeof Intl.supportedValuesOf === "function") {
            try {
                zones = Intl.supportedValuesOf("timeZone") || [];
            } catch (error) {
                zones = [];
            }
        }

        fallbackTimezones.forEach(function (zone) {
            if (zones.indexOf(zone) === -1) {
                zones.push(zone);
            }
        });

        zones.sort(function (left, right) {
            if (left === "UTC") {
                return -1;
            }

            if (right === "UTC") {
                return 1;
            }

            return left.localeCompare(right);
        });

        return zones;
    }

    function getBrowserDefaultTimezone() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        } catch (error) {
            return "UTC";
        }
    }

    function fillSelect(selector, selectedTimezone) {
        const select = $(selector);
        const value = selectedTimezone || "UTC";
        const zones = getBrowserTimezones();

        if (!select.length) {
            return;
        }

        select.empty();

        zones.forEach(function (zone) {
            $("<option>")
                .val(zone)
                .text(zone)
                .appendTo(select);
        });

        if (zones.indexOf(value) === -1) {
            $("<option>")
                .val(value)
                .text(value)
                .appendTo(select);
        }

        select.val(value);
    }

    function initSelect(selector, selectedTimezone, dropdownParent) {
        const select = $(selector);

        if (!select.length) {
            return;
        }

        fillSelect(select, selectedTimezone || "UTC");

        if (!$.fn.select2) {
            return;
        }

        if (select.hasClass("select2-hidden-accessible")) {
            select.select2("destroy");
        }

        select.select2({
            width: "100%",
            placeholder: "Select timezone",
            dropdownParent: dropdownParent ? $(dropdownParent) : undefined,
        });
    }

    function setSelectValue(selector, value) {
        const select = $(selector);
        const timezone = value || "UTC";

        if (!select.length) {
            return;
        }

        if (!select.find("option").filter(function () {
            return $(this).val() === timezone;
        }).length) {
            $("<option>")
                .val(timezone)
                .text(timezone)
                .appendTo(select);
        }

        select.val(timezone).trigger("change");
    }

    function getSelectValue(selector) {
        return $(selector).val() || "UTC";
    }

    function datetimeLocalNow(timezone) {
        const date = new Date();

        try {
            const parts = new Intl.DateTimeFormat("en-CA", {
                timeZone: timezone || "UTC",
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
                hourCycle: "h23",
            }).formatToParts(date);

            const values = {};

            parts.forEach(function (part) {
                if (part.type !== "literal") {
                    values[part.type] = part.value;
                }
            });

            return (
                values.year +
                "-" +
                values.month +
                "-" +
                values.day +
                "T" +
                values.hour +
                ":" +
                values.minute
            );
        } catch (error) {
            return date.toISOString().slice(0, 16);
        }
    }

    function normalizeDatetimeLocal(value) {
        const text = String(value || "").trim();

        if (!text) {
            return "";
        }

        if (text.length === 16) {
            return text + ":00";
        }

        return text;
    }

    function toDatetimeLocalInput(value) {
        if (!value) {
            return "";
        }

        const text = String(value);
        const match = text.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);

        if (!match) {
            return "";
        }

        return match[1] + "T" + match[2];
    }

    function formatPlainDatetime(value, timezone) {
        const inputValue = toDatetimeLocalInput(value);

        if (!inputValue) {
            return "-";
        }

        const parts = inputValue.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);

        if (!parts) {
            return inputValue;
        }

        const result = parts[3] + "/" + parts[2] + " " + parts[4] + ":" + parts[5];

        return timezone ? result + " " + timezone : result;
    }

    function normalizeTimezone(value) {
        const timezone = String(value || "").trim();

        return timezone || null;
    }

    function getUserTimezone(user) {
        if (!user) {
            return null;
        }

        return normalizeTimezone(user.timezone);
    }

    function getDisplayTimezone(user) {
        return (
            getUserTimezone(user) ||
            getBrowserDefaultTimezone() ||
            "UTC"
        );
    }

    function fillOptionalSelect(selector, selectedTimezone, emptyLabel) {
        const select = $(selector);
        const value = normalizeTimezone(selectedTimezone) || "";
        const browserTimezone = getBrowserDefaultTimezone();
        const zones = getBrowserTimezones();

        if (!select.length) {
            return;
        }

        select.empty();

        $("<option>")
            .val("")
            .text(
                emptyLabel ||
                ("Use browser timezone (" + browserTimezone + ")")
            )
            .appendTo(select);

        zones.forEach(function (zone) {
            $("<option>")
                .val(zone)
                .text(zone)
                .appendTo(select);
        });

        if (value && zones.indexOf(value) === -1) {
            $("<option>")
                .val(value)
                .text(value)
                .appendTo(select);
        }

        select.val(value);
    }

    function initOptionalSelect(selector, selectedTimezone, dropdownParent) {
        const select = $(selector);

        if (!select.length) {
            return;
        }

        fillOptionalSelect(select, selectedTimezone);

        if (!$.fn.select2) {
            return;
        }

        if (select.hasClass("select2-hidden-accessible")) {
            select.select2("destroy");
        }

        select.select2({
            width: "100%",
            placeholder: "Use browser timezone",
            allowClear: true,
            dropdownParent: dropdownParent ? $(dropdownParent) : undefined,
        });
    }

    function setOptionalSelectValue(selector, value) {
        const select = $(selector);
        const timezone = normalizeTimezone(value) || "";

        if (!select.length) {
            return;
        }

        if (
            timezone &&
            !select.find("option").filter(function () {
                return $(this).val() === timezone;
            }).length
        ) {
            $("<option>")
                .val(timezone)
                .text(timezone)
                .appendTo(select);
        }

        select.val(timezone).trigger("change");
    }

    function getOptionalSelectValue(selector) {
        return normalizeTimezone($(selector).val());
    }

    return {
        getBrowserTimezones: getBrowserTimezones,
        getBrowserDefaultTimezone: getBrowserDefaultTimezone,
        fillSelect: fillSelect,
        initSelect: initSelect,
        setSelectValue: setSelectValue,
        getSelectValue: getSelectValue,
        datetimeLocalNow: datetimeLocalNow,
        normalizeDatetimeLocal: normalizeDatetimeLocal,
        toDatetimeLocalInput: toDatetimeLocalInput,
        formatPlainDatetime: formatPlainDatetime,
        normalizeTimezone: normalizeTimezone,
        getUserTimezone: getUserTimezone,
        getDisplayTimezone: getDisplayTimezone,
        fillOptionalSelect: fillOptionalSelect,
        initOptionalSelect: initOptionalSelect,
        setOptionalSelectValue: setOptionalSelectValue,
        getOptionalSelectValue: getOptionalSelectValue,
    };
})();
