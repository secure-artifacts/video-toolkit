// ==UserScript==
// @name         ElevenLabs 凭证抓取（给 VideoToolkit 用）
// @namespace    videotoo-lkit.local
// @version      1.1.0
// @description  在 elevenlabs.io 登录后，自动拦截 api 请求头中的 xi-api-key / Authorization / Cookie，一键复制
// @author       VideoToolkit
// @match        https://elevenlabs.io/*
// @match        https://*.elevenlabs.io/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

/**
 * 安装方式（任选其一）：
 * 1) Tampermonkey / Violentmonkey：新建脚本 → 粘贴本文件全部内容 → 保存
 * 2) 不用扩展：打开 https://elevenlabs.io 并登录 → F12 → Console → 粘贴
 *    从「(function () {」到文件末尾的代码 → 回车
 *
 * 使用：
 * - 登录后刷新页面，或随便点进 Voice / Speech 等，触发 api 请求
 * - 右下角面板出现凭证后点「复制给 VideoToolkit」
 * - 在软件「设置 → 密钥 → 添加 ElevenLabs 网页会话」整段粘贴即可
 */
(function () {
  "use strict";

  const state = {
    xiApiKey: "",
    authorization: "",
    cookie: "",
    lastUrl: "",
    hits: 0,
  };

  function isElevenApi(url) {
    try {
      const u = String(url || "");
      return (
        u.includes("api.elevenlabs.io") ||
        u.includes("api.us.elevenlabs.io") ||
        u.includes("api.eu.elevenlabs.io")
      );
    } catch (_) {
      return false;
    }
  }

  function pickHeader(headers, name) {
    if (!headers) return "";
    const want = name.toLowerCase();
    if (typeof headers.get === "function") {
      return headers.get(name) || headers.get(want) || "";
    }
    if (Array.isArray(headers)) {
      // [[k,v], ...]
      for (const pair of headers) {
        if (pair && String(pair[0]).toLowerCase() === want) return String(pair[1] || "");
      }
      return "";
    }
    if (typeof headers === "object") {
      for (const k of Object.keys(headers)) {
        if (k.toLowerCase() === want) return String(headers[k] || "");
      }
    }
    return "";
  }

  function absorb(url, headers) {
    if (!isElevenApi(url) || !headers) return;
    const xi =
      pickHeader(headers, "xi-api-key") ||
      pickHeader(headers, "x-api-key") ||
      pickHeader(headers, "Xi-Api-Key");
    const auth = pickHeader(headers, "authorization") || pickHeader(headers, "Authorization");
    const cookie = pickHeader(headers, "cookie") || pickHeader(headers, "Cookie");

    let changed = false;
    if (xi && xi !== state.xiApiKey) {
      state.xiApiKey = xi.trim();
      changed = true;
    }
    if (auth && auth !== state.authorization) {
      state.authorization = auth.trim();
      changed = true;
    }
    if (cookie && cookie.length > 20) {
      state.cookie = cookie.trim();
      changed = true;
    }
    if (changed || xi || auth) {
      state.lastUrl = String(url);
      state.hits += 1;
      render();
    }
  }

  // ---- 拦截 fetch ----
  const _fetch = window.fetch;
  if (typeof _fetch === "function") {
    window.fetch = function (input, init) {
      try {
        const url = typeof input === "string" ? input : input && input.url;
        const headers =
          (init && init.headers) ||
          (input && typeof input.headers !== "undefined" ? input.headers : null);
        absorb(url, headers);
      } catch (_) {}
      return _fetch.apply(this, arguments);
    };
  }

  // ---- 拦截 XHR ----
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.setRequestHeader;
  const XSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__el_url = url;
    this.__el_headers = {};
    return XO.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    try {
      if (!this.__el_headers) this.__el_headers = {};
      this.__el_headers[name] = value;
    } catch (_) {}
    return XS.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    try {
      absorb(this.__el_url, this.__el_headers);
    } catch (_) {}
    return XSend.apply(this, arguments);
  };

  // 也尝试从 document.cookie 补一份（通常不够鉴权，但可附带）
  function refreshDocCookie() {
    try {
      if (document.cookie && document.cookie.length > 10) {
        if (!state.cookie || state.cookie.length < document.cookie.length) {
          state.cookie = document.cookie;
        }
      }
    } catch (_) {}
  }

  function buildExportText() {
    refreshDocCookie();
    const lines = [];
    lines.push("# VideoToolkit ElevenLabs 网页会话（由抓取脚本生成）");
    lines.push("# 请整段复制到软件 → 设置与组件 → 密钥 → 添加 ElevenLabs 网页会话");
    lines.push("# 可直接贴进「Cookie / 请求头」大框，软件会自动识别字段");
    lines.push("");
    if (state.xiApiKey) lines.push("xi-api-key: " + state.xiApiKey);
    if (state.authorization) lines.push("authorization: " + state.authorization);
    if (state.cookie) lines.push("cookie: " + state.cookie);
    if (!state.xiApiKey && !state.authorization) {
      lines.push("# 尚未抓到 xi-api-key / Authorization。请刷新页面或点进 Speech / Voices 触发请求。");
    }
    if (state.lastUrl) lines.push("# last: " + state.lastUrl);
    return lines.join("\n");
  }

  function mask(s) {
    s = String(s || "");
    if (s.length <= 12) return s ? "•••" : "（无）";
    return s.slice(0, 6) + "…" + s.slice(-4);
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (e) {
        reject(e);
      } finally {
        document.body.removeChild(ta);
      }
    });
  }

  let panel;
  function ensurePanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = document.createElement("div");
    panel.id = "vt-el-capture-panel";
    panel.innerHTML = [
      '<div style="font-weight:800;margin-bottom:6px;">VideoToolkit · ElevenLabs 凭证</div>',
      '<div id="vt-el-status" style="font-size:12px;line-height:1.45;opacity:.95;margin-bottom:8px;"></div>',
      '<button id="vt-el-copy" style="width:100%;padding:8px 10px;border:0;border-radius:8px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer;margin-bottom:6px;">复制给 VideoToolkit</button>',
      '<button id="vt-el-refresh" style="width:100%;padding:6px 10px;border:1px solid #475569;border-radius:8px;background:#0f172a;color:#e2e8f0;cursor:pointer;margin-bottom:6px;">刷新显示</button>',
      '<div style="font-size:11px;opacity:.8;line-height:1.4;">登录后刷新或点 Voices/Speech。优先出现 xi-api-key 即可。</div>',
    ].join("");
    Object.assign(panel.style, {
      position: "fixed",
      right: "16px",
      bottom: "16px",
      width: "300px",
      zIndex: "2147483646",
      background: "rgba(15,23,42,.96)",
      color: "#f1f5f9",
      border: "1px solid #334155",
      borderRadius: "12px",
      padding: "12px",
      boxShadow: "0 12px 40px rgba(0,0,0,.45)",
      fontFamily: "system-ui,Segoe UI,sans-serif",
    });
    document.documentElement.appendChild(panel);
    panel.querySelector("#vt-el-copy").onclick = function () {
      const text = buildExportText();
      copyText(text).then(
        function () {
          panel.querySelector("#vt-el-copy").textContent = "✓ 已复制，去软件粘贴";
          setTimeout(function () {
            panel.querySelector("#vt-el-copy").textContent = "复制给 VideoToolkit";
          }, 2000);
        },
        function () {
          prompt("复制失败，请手动全选复制：", text);
        }
      );
    };
    panel.querySelector("#vt-el-refresh").onclick = function () {
      refreshDocCookie();
      render();
    };
    return panel;
  }

  function render() {
    try {
      if (!document.body && !document.documentElement) return;
      ensurePanel();
      const el = panel.querySelector("#vt-el-status");
      const ok = !!(state.xiApiKey || state.authorization);
      el.innerHTML =
        "抓取次数: <b>" +
        state.hits +
        "</b><br/>" +
        "xi-api-key: <b style='color:" +
        (state.xiApiKey ? "#4ade80" : "#f87171") +
        "'>" +
        mask(state.xiApiKey) +
        "</b><br/>" +
        "Authorization: <b style='color:" +
        (state.authorization ? "#4ade80" : "#94a3b8") +
        "'>" +
        mask(state.authorization) +
        "</b><br/>" +
        "Cookie: <b>" +
        (state.cookie ? "已捕获 " + state.cookie.length + " 字符" : "（无/较短）") +
        "</b><br/>" +
        (ok
          ? "<span style='color:#4ade80'>可以复制到软件了</span>"
          : "<span style='color:#fbbf24'>请刷新页面或点站内功能触发 API</span>");
    } catch (_) {}
  }

  // 页面就绪后显示面板
  function boot() {
    render();
    // 周期性尝试（有的请求头在页面脚本里设置）
    setInterval(function () {
      refreshDocCookie();
      render();
    }, 3000);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  console.log(
    "[VideoToolkit] ElevenLabs 凭证抓取已启用。登录后刷新页面，右下角面板可复制。"
  );
})();
