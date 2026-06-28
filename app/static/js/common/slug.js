(function () {
    const CYRILLIC_MAP = {
        а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e",
        ж: "zh", з: "z", и: "i", й: "y", к: "k", л: "l", м: "m",
        н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u",
        ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch",
        ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
    };

    function transliterate(value) {
        return String(value || "")
            .split("")
            .map(function (char) {
                const lower = char.toLowerCase();
                const mapped = CYRILLIC_MAP[lower];

                if (mapped === undefined) {
                    return char;
                }

                return char === lower ? mapped : mapped.toUpperCase();
            })
            .join("");
    }

    function slugify(value) {
        return transliterate(value)
            .toLowerCase()
            .trim()
            .replace(/['"`]/g, "")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .replace(/-{2,}/g, "-");
    }

    function markManual(targetSelector, manual) {
        $(targetSelector).data("slug-manual", !!manual);
    }

    function isManual(targetSelector) {
        return $(targetSelector).data("slug-manual") === true;
    }

    function update(sourceSelector, targetSelector, options) {
        options = options || {};

        const source = $(sourceSelector);
        const target = $(targetSelector);

        if (!source.length || !target.length) {
            return;
        }

        if (isManual(targetSelector) && !options.force) {
            return;
        }

        const value = slugify(source.val());

        target.val(value);
        target.data("slug-last-auto", value);
    }

    function reset(targetSelector, options) {
        options = options || {};

        const target = $(targetSelector);

        target.data("slug-manual", !!options.manual);
        target.data("slug-last-auto", target.val() || "");
    }

    function bind(sourceSelector, targetSelector, options) {
        options = options || {};

        const source = $(sourceSelector);
        const target = $(targetSelector);

        if (!source.length || !target.length) {
            return;
        }

        source.off(".slugAutofill");
        target.off(".slugAutofill");

        reset(targetSelector, {
            manual: !!target.val() && options.manualWhenHasValue !== false,
        });

        source.on("input.slugAutofill change.slugAutofill", function () {
            update(sourceSelector, targetSelector);
        });

        target.on("input.slugAutofill change.slugAutofill", function () {
            const current = target.val();
            const autoValue = slugify(source.val());

            if (!current) {
                markManual(targetSelector, false);
                update(sourceSelector, targetSelector);
                return;
            }

            markManual(targetSelector, current !== autoValue);
            target.data("slug-last-auto", autoValue);
        });

        if (options.initialUpdate) {
            update(sourceSelector, targetSelector);
        }
    }

    window.AppSlug = {
        slugify: slugify,
        bind: bind,
        reset: reset,
        update: update,
    };
})();
