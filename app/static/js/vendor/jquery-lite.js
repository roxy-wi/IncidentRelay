(function () {
    "use strict";

    function toArray(value) {
        return Array.prototype.slice.call(value || []);
    }

    function createElementFromHtml(selector) {
        var match = selector.match(/^<([a-zA-Z0-9-]+)>$/);
        if (!match) {
            return null;
        }

        return document.createElement(match[1]);
    }

    function JQueryLite(elements) {
        this.elements = elements || [];
        this.length = this.elements.length;

        for (var i = 0; i < this.elements.length; i += 1) {
            this[i] = this.elements[i];
        }
    }

    function $(selector) {
        if (selector instanceof JQueryLite) {
            return selector;
        }

        if (typeof selector === "function") {
            return $(document).ready(selector);
        }

        if (selector === document || selector === window) {
            return new JQueryLite([selector]);
        }

        if (selector instanceof Node) {
            return new JQueryLite([selector]);
        }

        if (Array.isArray(selector)) {
            return new JQueryLite(selector);
        }

        if (typeof selector === "string") {
            var created = createElementFromHtml(selector.trim());

            if (created) {
                return new JQueryLite([created]);
            }

            try {
                if (selector.indexOf(":first") !== -1) {
                    return new JQueryLite(toArray(document.querySelectorAll(selector.replace(":first", ":first-child"))));
                }

                return new JQueryLite(toArray(document.querySelectorAll(selector)));
            } catch (error) {
                console.error("Invalid selector:", selector, error);
                return new JQueryLite([]);
            }
        }

        return new JQueryLite([]);
    }

    JQueryLite.prototype.each = function (callback) {
        this.elements.forEach(function (element, index) {
            callback.call(element, index, element);
        });
        return this;
    };

    JQueryLite.prototype.ready = function (callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
        return this;
    };

    JQueryLite.prototype.on = function (eventName, selectorOrHandler, handler) {
        if (typeof selectorOrHandler === "function") {
            return this.each(function () {
                this.addEventListener(eventName, selectorOrHandler);
            });
        }

        return this.each(function () {
            this.addEventListener(eventName, function (event) {
                var target = event.target.closest(selectorOrHandler);

                if (target && this.contains(target) && typeof handler === "function") {
                    handler.call(target, event);
                }
            });
        });
    };

    JQueryLite.prototype.append = function (child) {
        var childElements;

        if (child instanceof JQueryLite) {
            childElements = child.elements;
        } else if (child instanceof Node) {
            childElements = [child];
        } else {
            childElements = [document.createTextNode(String(child))];
        }

        return this.each(function () {
            var parent = this;
            childElements.forEach(function (node) {
                parent.appendChild(node);
            });
        });
    };

    JQueryLite.prototype.empty = function () {
        return this.each(function () {
            this.innerHTML = "";
        });
    };

    JQueryLite.prototype.text = function (value) {
        if (value === undefined) {
            return this.elements[0] ? this.elements[0].textContent : "";
        }

        return this.each(function () {
            this.textContent = value;
        });
    };

    JQueryLite.prototype.html = function (value) {
        if (value === undefined) {
            return this.elements[0] ? this.elements[0].innerHTML : "";
        }

        return this.each(function () {
            this.innerHTML = value;
        });
    };

    JQueryLite.prototype.val = function (value) {
        var element;

        if (value === undefined) {
            element = this.elements[0];

            if (!element) {
                return "";
            }

            if (element.multiple) {
                return toArray(element.options)
                    .filter(function (option) { return option.selected; })
                    .map(function (option) { return option.value; });
            }

            return element.value;
        }

        return this.each(function () {
            var values;

            if (this.multiple && Array.isArray(value)) {
                values = value.map(String);
                toArray(this.options).forEach(function (option) {
                    option.selected = values.indexOf(option.value) !== -1;
                });
                return;
            }

            this.value = value;
        });
    };

    JQueryLite.prototype.attr = function (name, value) {
        if (value === undefined) {
            return this.elements[0] ? this.elements[0].getAttribute(name) : undefined;
        }

        return this.each(function () {
            this.setAttribute(name, value);
        });
    };

    JQueryLite.prototype.prop = function (name, value) {
        if (value === undefined) {
            return this.elements[0] ? this.elements[0][name] : undefined;
        }

        return this.each(function () {
            this[name] = value;
        });
    };

    JQueryLite.prototype.addClass = function (className) {
        return this.each(function () {
            this.classList.add.apply(this.classList, String(className).split(/\s+/).filter(Boolean));
        });
    };

    JQueryLite.prototype.removeClass = function (className) {
        return this.each(function () {
            this.classList.remove.apply(this.classList, String(className).split(/\s+/).filter(Boolean));
        });
    };

    JQueryLite.prototype.hide = function () {
        return this.each(function () {
            this.style.display = "none";
        });
    };

    JQueryLite.prototype.show = function () {
        return this.each(function () {
            this.style.display = "";
        });
    };

    JQueryLite.prototype.toggle = function (visible) {
        return visible ? this.show() : this.hide();
    };

    JQueryLite.prototype.css = function (name, value) {
        if (value === undefined) {
            return this.elements[0] ? window.getComputedStyle(this.elements[0])[name] : undefined;
        }

        return this.each(function () {
            this.style[name] = value;
        });
    };

    JQueryLite.prototype.is = function (selector) {
        var element = this.elements[0];

        if (!element) {
            return false;
        }

        if (selector === ":checked") {
            return !!element.checked;
        }

        return element.matches(selector);
    };

    JQueryLite.prototype.find = function (selector) {
        var result = [];

        this.each(function () {
            result = result.concat(toArray(this.querySelectorAll(selector)));
        });

        return new JQueryLite(result);
    };

    JQueryLite.prototype.closest = function (selector) {
        if (!this.elements[0]) {
            return new JQueryLite([]);
        }

        return new JQueryLite([this.elements[0].closest(selector)].filter(Boolean));
    };

    $.ajax = function (options) {
        var method = options.method || options.type || "GET";
        var headers = options.headers || {};
        var body;

        if (options.contentType) {
            headers["Content-Type"] = options.contentType;
        }

        if (options.data !== undefined) {
            body = options.data;
        }

        fetch(options.url, {
            method: method,
            headers: headers,
            body: body,
            credentials: "same-origin"
        }).then(function (response) {
            return response.text().then(function (text) {
                var data = text;

                try {
                    data = text ? JSON.parse(text) : null;
                } catch (error) {
                    data = text;
                }

                if (!response.ok) {
                    if (typeof options.error === "function") {
                        options.error({
                            status: response.status,
                            responseText: text,
                            responseJSON: data
                        });
                    }
                    return;
                }

                if (typeof options.success === "function") {
                    options.success(data, "success", response);
                }
            });
        }).catch(function (error) {
            if (typeof options.error === "function") {
                options.error({
                    status: 0,
                    responseText: String(error)
                });
            }
        });
    };

    window.$ = window.jQuery = $;
}());
