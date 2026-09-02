// ==UserScript==
// @name         TypeType Wayland 物理击键桥接
// @namespace    https://github.com/whynusn/typetype
// @version      0.3.0
// @description  修正我爱打字网在 Wayland 中文输入法下的物理击键统计
// @match        https://www.52dazi.cn/*
// @match        https://52dazi.cn/*
// @connect      127.0.0.1
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// ==/UserScript==

(function () {
    "use strict";

    // 将本机服务启动时打印的 token 填到这里。不要把 token 提交到公共仓库。
    const CONFIG = {
        token: "PASTE_TOKEN_HERE",
        endpoint: "http://127.0.0.1:8765",
        allowedHosts: ["www.52dazi.cn", "52dazi.cn"],
        showBadge: true,
    };

    const EVENT_NAME = "typetype:physical-key";
    const MESSAGE_SOURCE = "typetype-wayland-bridge";
    const RECONNECT_DELAY_MS = 2500;
    const PAIR_WINDOW_MS = 500;
    const TOKEN_PLACEHOLDER = "PASTE_TOKEN_HERE";
    const PAGE_WINDOW = typeof unsafeWindow === "undefined" ? window : unsafeWindow;
    const NATIVE_QUEUES = { stroke: [], backspace: [] };
    const PHYSICAL_QUEUES = { stroke: [], backspace: [] };
    const IGNORED_CODES = new Set([
        "ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
        "AltLeft", "AltRight", "MetaLeft", "MetaRight", "CapsLock",
        "Home", "ArrowUp", "PageUp", "ArrowLeft", "ArrowRight",
        "End", "ArrowDown", "PageDown", "Insert", "Delete",
    ]);
    let bridgeConnected = false;
    let pollCursor = -1;
    let pollRequest = null;
    let reconnectTimer = null;
    let badge = null;
    let activeTarget = null;
    let stats = { strokes: 0, backspaces: 0, startedAt: 0 };
    let status = "未连接";

    function isAllowedHost() {
        return CONFIG.allowedHosts.length === 0 || CONFIG.allowedHosts.includes(location.hostname);
    }

    function isEditable(element) {
        if (!element || !(element instanceof PAGE_WINDOW.Element)) {
            return false;
        }
        if (element instanceof PAGE_WINDOW.HTMLTextAreaElement) {
            return true;
        }
        if (element instanceof PAGE_WINDOW.HTMLInputElement) {
            return !["button", "checkbox", "file", "hidden", "radio", "range", "submit", "password"].includes(element.type);
        }
        return element.isContentEditable;
    }

    function textLength(element) {
        if (
            element instanceof PAGE_WINDOW.HTMLInputElement ||
            element instanceof PAGE_WINDOW.HTMLTextAreaElement
        ) {
            return element.value.length;
        }
        return (element.innerText || element.textContent || "").length;
    }

    function resetSession(target) {
        activeTarget = target;
        stats = { strokes: 0, backspaces: 0, startedAt: performance.now() };
    }

    function currentTarget() {
        if (document.visibilityState !== "visible") {
            return null;
        }
        const target = document.activeElement;
        return isEditable(target) ? target : null;
    }

    function resolvePractice() {
        const root = PAGE_WINDOW.document.querySelector("#practice");
        const input = root && root.querySelector("input.input.el-input__inner");
        const vm = root && root.__vue__;
        if (!root || !input || !vm || !Array.isArray(vm.phrases)) {
            return null;
        }
        return { input: input, vm: vm };
    }

    function resolveRacing() {
        const home = PAGE_WINDOW.document.querySelector("#home");
        const racingVm = home && home.__vue__ && home.__vue__.$refs.racing;
        const textarea = PAGE_WINDOW.document.querySelector("#racing-textarea");
        const store = racingVm && racingVm.$store;
        const state = store && store.state && store.state.racing;
        if (!home || !racingVm || !textarea || !store || !state) {
            return null;
        }
        return { racingVm: racingVm, textarea: textarea, store: store, state: state };
    }

    function siteContextForTarget(target) {
        const practice = resolvePractice();
        if (practice && practice.input === target) {
            return { page: "practice", context: practice };
        }
        const racing = resolveRacing();
        if (racing && racing.textarea === target) {
            return { page: "racing", context: racing };
        }
        return null;
    }

    function browserKeyKind(event) {
        if (event.repeat || IGNORED_CODES.has(event.code)) {
            return null;
        }
        if ((event.ctrlKey || event.metaKey) && event.code !== "Backspace") {
            return null;
        }
        return event.code === "Backspace" ? "backspace" : "stroke";
    }

    function takePairedEvent(queue, timestamp) {
        while (queue.length && timestamp - queue[0].timestamp > PAIR_WINDOW_MS * 4) {
            queue.shift();
        }
        const index = queue.findIndex(function (item) {
            return Math.abs(item.timestamp - timestamp) <= PAIR_WINDOW_MS;
        });
        return index >= 0 ? queue.splice(index, 1)[0] : null;
    }

    function clearPairingQueues() {
        NATIVE_QUEUES.stroke.length = 0;
        NATIVE_QUEUES.backspace.length = 0;
        PHYSICAL_QUEUES.stroke.length = 0;
        PHYSICAL_QUEUES.backspace.length = 0;
    }

    function counterValue(site, code) {
        if (site.page === "practice") {
            return Number(site.context.vm.keyCount || 0);
        }
        const state = site.context.state;
        return Array.isArray(state.keys) ? state.keys.length : 0;
    }

    function rollbackNativeCount(site, code, beforeCodeCount) {
        if (site.page === "practice") {
            site.context.vm.keyCount = Math.max(0, Number(site.context.vm.keyCount || 0) - 1);
            site.context.vm.lastKeyCount = Math.max(0, Number(site.context.vm.lastKeyCount || 0) - 1);
            return;
        }
        const context = site.context;
        const keys = context.state.keys;
        const index = keys.lastIndexOf(code);
        if (index >= 0) {
            keys.splice(index, 1);
        }
        context.racingVm.$set(context.state.keyCount, code, beforeCodeCount);
    }

    function observeNativeKeydown(event) {
        if (!event.isTrusted || !bridgeConnected) {
            return;
        }
        const site = siteContextForTarget(event.target);
        if (!site) {
            return;
        }
        const kind = browserKeyKind(event);
        const before = counterValue(site, event.code);
        const beforeCodeCount = site.page === "racing"
            ? Number(site.context.state.keyCount[event.code] || 0)
            : 0;
        const timestamp = Date.now();
        queueMicrotask(function () {
            if (counterValue(site, event.code) <= before) {
                return;
            }
            if (!kind) {
                rollbackNativeCount(site, event.code, beforeCodeCount);
                return;
            }
            if (takePairedEvent(PHYSICAL_QUEUES[kind], timestamp)) {
                rollbackNativeCount(site, event.code, beforeCodeCount);
                return;
            }
            NATIVE_QUEUES[kind].push({ timestamp: timestamp });
        });
    }

    function injectPracticeKey(context) {
        if (document.activeElement !== context.input || !context.vm.phrases.length) {
            return false;
        }
        context.vm.keyCount += 1;
        context.vm.lastKeyCount += 1;
        return true;
    }

    function injectRacingKey(context, kind) {
        if (
            document.activeElement !== context.textarea ||
            context.textarea.disabled ||
            !["init", "typing"].includes(context.state.status)
        ) {
            return false;
        }
        context.store.dispatch("racing/typing", {
            code: kind === "backspace" ? "Backspace" : "Unidentified",
            isComposing: false,
            repeat: false,
            __typetypePhysical: true,
        });
        return true;
    }

    function injectSiteKey(kind, timestamp) {
        const target = currentTarget();
        const site = target && siteContextForTarget(target);
        if (!site) {
            return;
        }
        if (takePairedEvent(NATIVE_QUEUES[kind], timestamp)) {
            return;
        }
        const injected = site.page === "practice"
            ? injectPracticeKey(site.context)
            : injectRacingKey(site.context, kind);
        if (injected) {
            PHYSICAL_QUEUES[kind].push({ timestamp: timestamp });
        }
    }

    function consumeKey(kind, timestamp) {
        const target = currentTarget();
        if (!target) {
            updateBadge();
            return;
        }
        if (target !== activeTarget) {
            resetSession(target);
        }
        if (kind === "backspace") {
            stats.backspaces += 1;
            stats.strokes += 1;
        } else if (kind === "stroke") {
            stats.strokes += 1;
        } else {
            return;
        }
        if (is52daziHost()) {
            injectSiteKey(kind, Number(timestamp || Date.now()));
        }
        dispatchPhysicalKey(kind, target);
    }

    function is52daziHost() {
        return location.hostname === "52dazi.cn" || location.hostname === "www.52dazi.cn";
    }

    function badgeText() {
        if (status !== "已连接") {
            return "Wayland bridge: " + status;
        }
        const chars = activeTarget ? textLength(activeTarget) : 0;
        const codeLength = chars > 0 ? (stats.strokes / chars).toFixed(2) : "0.00";
        return "物理击键 " + stats.strokes + " · 退格 " + stats.backspaces + " · 码长 " + codeLength;
    }

    function updateBadge() {
        if (!CONFIG.showBadge || !badge) {
            return;
        }
        badge.textContent = badgeText();
        badge.dataset.status = status;
    }

    function createBadge() {
        if (!CONFIG.showBadge || badge || !document.documentElement) {
            return;
        }
        badge = document.createElement("div");
        badge.id = "typetype-wayland-bridge-status";
        badge.style.cssText = [
            "position:fixed", "z-index:2147483647", "right:12px", "bottom:12px",
            "padding:5px 8px", "border:1px solid #888", "border-radius:4px",
            "background:#202124", "color:#e8eaed", "font:12px/1.4 sans-serif",
            "opacity:.86", "pointer-events:none", "box-shadow:0 1px 4px #0005",
        ].join(";");
        document.documentElement.appendChild(badge);
        updateBadge();
    }

    function setStatus(nextStatus) {
        status = nextStatus;
        createBadge();
        updateBadge();
    }

    function schedulePoll(delay) {
        if (reconnectTimer || !isAllowedHost()) {
            return;
        }
        reconnectTimer = window.setTimeout(function () {
            reconnectTimer = null;
            pollEvents();
        }, delay);
    }

    function markDisconnected(nextStatus) {
        bridgeConnected = false;
        pollCursor = -1;
        pollRequest = null;
        clearPairingQueues();
        setStatus(nextStatus);
        schedulePoll(RECONNECT_DELAY_MS);
    }

    function pollEvents() {
        if (!isAllowedHost() || !CONFIG.token || CONFIG.token === TOKEN_PLACEHOLDER) {
            setStatus("未配置 token");
            return;
        }
        if (pollRequest) {
            return;
        }
        if (!bridgeConnected) {
            setStatus("连接中");
        }
        const url = CONFIG.endpoint + "/events?token=" + encodeURIComponent(CONFIG.token) + "&since=" + pollCursor;
        pollRequest = GM_xmlhttpRequest({
            method: "GET",
            url: url,
            headers: { "X-Typetype-Origin": location.origin },
            timeout: 30000,
            onload: function (response) {
                pollRequest = null;
                if (response.status !== 200) {
                    markDisconnected(response.status === 403 ? "token 或 Origin 错误" : "服务错误");
                    return;
                }
                try {
                    const data = JSON.parse(response.responseText);
                    if (!Array.isArray(data.events) || typeof data.cursor !== "number") {
                        throw new Error("invalid bridge response");
                    }
                    bridgeConnected = true;
                    setStatus("已连接");
                    data.events.forEach(function (event) {
                        if (event.type === "key") {
                            consumeKey(event.kind, event.timestamp);
                        }
                    });
                    pollCursor = data.cursor;
                    schedulePoll(0);
                } catch (_) {
                    markDisconnected("协议错误");
                }
            },
            onerror: function () {
                markDisconnected("未连接");
            },
            ontimeout: function () {
                markDisconnected("连接超时");
            },
        });
    }

    function dispatchPhysicalKey(kind, target) {
        const payload = {
            version: 1,
            kind: kind,
            timestamp: Date.now(),
            strokes: stats.strokes,
            backspaces: stats.backspaces,
            textLength: textLength(target),
        };

        try {
            PAGE_WINDOW.document.dispatchEvent(
                new PAGE_WINDOW.CustomEvent(EVENT_NAME, { detail: JSON.stringify(payload) })
            );
            PAGE_WINDOW.postMessage(
                { source: MESSAGE_SOURCE, type: "physical-key", payload: payload },
                location.origin
            );
        } catch (_) {
            // 站点适配不依赖外部事件，跨用户脚本隔离失败时继续统计。
        }
        updateBadge();
    }

    function onFocusIn(event) {
        if (isEditable(event.target) && event.target !== activeTarget) {
            resetSession(event.target);
        }
        updateBadge();
    }

    function onFocusOut() {
        updateBadge();
    }

    if (!isAllowedHost()) {
        return;
    }
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("keydown", observeNativeKeydown, true);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", createBadge, { once: true });
    } else {
        createBadge();
    }
    pollEvents();
    window.addEventListener("beforeunload", function () {
        if (pollRequest && typeof pollRequest.abort === "function") {
            pollRequest.abort();
        }
    });
})();
