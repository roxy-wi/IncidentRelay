function padDateTimePart(value) {
    /*
     * Return a date/time part as a two-digit string.
     */
    return String(value).padStart(2, "0");
}
const dateTimeFormattersCache = {};


function getBrowserLocales() {
    /*
     * Return browser-preferred locales for date/time formatting.
     */
    if (navigator.languages && navigator.languages.length) {
        return navigator.languages;
    }

    if (navigator.language) {
        return navigator.language;
    }

    return "en-GB";
}


function parseDisplayDate(value) {
    /*
     * Parse an API datetime value or Date object.
     */
    if (!value) {
        return null;
    }

    const date = value instanceof Date ? value : new Date(value);

    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return date;
}


function getDateTimeFormatter(kind, overrides) {
    /*
     * Return cached browser-locale formatter.
     */
    const locales = getBrowserLocales();

    const optionsByKind = {
        date: {
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
        },
        shortDate: {
            month: "2-digit",
            day: "2-digit"
        },
        time: {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        },
        timeMinutes: {
            hour: "2-digit",
            minute: "2-digit"
        },
        dateTime: {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        },
        dateTimeMinutes: {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        },
        shortDateTimeMinutes: {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    };

    const options = Object.assign(
        {},
        optionsByKind[kind] || optionsByKind.dateTime,
        overrides || {}
    );

    const cacheKey = kind
        + ":"
        + JSON.stringify(locales)
        + ":"
        + JSON.stringify(options);

    if (dateTimeFormattersCache[cacheKey]) {
        return dateTimeFormattersCache[cacheKey];
    }

    dateTimeFormattersCache[cacheKey] = new Intl.DateTimeFormat(
        locales,
        options
    );

    return dateTimeFormattersCache[cacheKey];
}


function formatBrowserDate(value, kind, overrides) {
    /*
     * Format date/time using browser locale preferences.
     */
    const date = parseDisplayDate(value);

    if (!date) {
        return "-";
    }

    return getDateTimeFormatter(kind || "dateTime", overrides).format(date);
}

function formatBrowserDateInTimezone(value, kind, timezone) {
    /*
     * Format date/time in a specific IANA timezone.
     */
    return formatBrowserDate(
        value,
        kind,
        {
            timeZone: timezone || "UTC",
            hour12: false
        }
    );
}

function formatTimeMinutesInTimezone(value, timezone) {
    /*
     * Format HH:mm in a specific IANA timezone.
     */
    return formatBrowserDateInTimezone(value, "timeMinutes", timezone);
}

function formatDateTimeMinutesInTimezone(value, timezone) {
    /*
     * Format full date/time without seconds in a specific IANA timezone.
     */
    return formatBrowserDateInTimezone(value, "dateTimeMinutes", timezone);
}

function formatShortDateTimeMinutesInTimezone(value, timezone) {
    /*
     * Format short date/time without seconds in a specific IANA timezone.
     */
    return formatBrowserDateInTimezone(value, "shortDateTimeMinutes", timezone);
}


function formatDate(value) {
    /*
     * Format date using browser locale.
     */
    return formatBrowserDate(value, "date");
}


function formatShortDate(value) {
    /*
     * Format short date using browser locale.
     */
    return formatBrowserDate(value, "shortDate");
}


function formatDateTime(value) {
    /*
     * Format datetime using browser locale.
     */
    return formatBrowserDate(value, "dateTime");
}

function formatDateTimeMinutes(value) {
    /*
     * Format datetime without seconds using browser locale.
     */
    return formatBrowserDate(value, "dateTimeMinutes");
}


/*
 * Temporary compatibility wrapper for old code.
 * It no longer forces 24-hour format; browser settings decide that.
 */
function formatDateTime24(value, options) {
    if (options && options.seconds === false) {
        return formatDateTimeMinutes(value);
    }

    return formatDateTime(value);
}
function isoToDatetimeLocal(value) {
    /* Convert an ISO date string to datetime-local format. */
    if (!value) { return ""; }
    return value.slice(0, 16);
}
