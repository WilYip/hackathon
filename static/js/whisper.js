// 温柔传话页面脚本
// - 每 4 秒轮询新消息（页面在后台标签页时暂停）
// - 温柔转达：等待动画 → 预览（就这样发 / 我再改改 / 取消）→ 发送
// - 直接发送、和好、拥抱动画、API key 弹窗
// 所有消息文字都用 textContent 放进页面，不会被当成 HTML 执行
// 声音都交给全站声音管理器（static/js/sound.js）；声音出错不会影响聊天
(function () {
  var root = document.querySelector("[data-whisper]");
  if (!root) return;

  var S = JSON.parse(document.getElementById("whisper-strings").textContent);
  var lang = root.dataset.lang === "en" ? "en-AU" : "zh-CN";
  var reduceMotion = window.uslandReduceMotion ? window.uslandReduceMotion() : false;
  // 电脑（有鼠标）：Enter 发送、Shift+Enter 换行；手机：Enter 换行
  var enterSends = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  var $ = function (sel) {
    return document.querySelector(sel);
  };
  var log = $("[data-chat-log]");
  var input = $("[data-input]");
  var composer = $("[data-composer]");
  var composerError = $("[data-composer-error]");
  var dlgKey = document.getElementById("dlg-key");
  var dlgPreview = document.getElementById("dlg-preview");
  var dlgSafety = document.getElementById("dlg-safety");

  // 声音管理器（万一没加载，就用什么都不做的替身）
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop };

  var lastId = 0;
  var hugId = parseInt(root.dataset.hugId, 10) || 0;
  var needsKey = root.dataset.needsKey === "1";
  var pollTimer = null;
  var busy = false;

  // ---------- 小工具 ----------

  // 发 JSON 请求；登录过期时刷新页面（会跳到登录页）
  function api(url, body) {
    var options = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    return fetch(url, options).then(function (resp) {
      if (resp.status === 401) {
        window.location.reload();
        throw new Error("login_required");
      }
      return resp.json().then(function (data) {
        data._status = resp.status;
        return data;
      });
    });
  }

  function formatTime(iso) {
    var d = new Date(iso);
    var now = new Date();
    var time = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return time;
    return d.toLocaleDateString(lang, { month: "short", day: "numeric" }) + " " + time;
  }

  function showStep(name) {
    dlgPreview.querySelectorAll("[data-preview-step]").forEach(function (el) {
      el.hidden = el.dataset.previewStep !== name;
    });
  }

  function openDialog(dlg) {
    if (!dlg.open) dlg.showModal();
  }

  // 点击弹窗外的背景关闭（Esc 关闭由浏览器自带）
  [dlgKey, dlgPreview, dlgSafety].forEach(function (dlg) {
    dlg.addEventListener("click", function (event) {
      if (event.target === dlg && !busy) dlg.close();
    });
  });

  // ---------- 消息列表 ----------

  function renderMessage(m) {
    if (log.querySelector('[data-id="' + m.id + '"]')) return; // 已经显示过
    var row = document.createElement("div");
    row.className = "msg " + (m.mine ? "msg-mine" : "msg-theirs");
    row.dataset.id = m.id;

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    var text = document.createElement("p");
    text.className = "bubble-text";
    text.textContent = m.text;
    bubble.appendChild(text);

    // 原话：只有发送者本人收到这个字段
    if (m.original) {
      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "original-toggle";
      toggle.textContent = S.show_original;
      var original = document.createElement("p");
      original.className = "bubble-original";
      original.hidden = true;
      original.textContent = S.original_label + m.original; // "原话：" / "Original: "
      toggle.addEventListener("click", function () {
        original.hidden = !original.hidden;
        toggle.textContent = original.hidden ? S.show_original : S.hide_original;
      });
      bubble.appendChild(original);
      bubble.appendChild(toggle);
    }

    var meta = document.createElement("time");
    meta.className = "msg-time";
    meta.dateTime = m.time;
    meta.textContent = formatTime(m.time);

    row.appendChild(bubble);
    row.appendChild(meta);
    log.appendChild(row);
  }

  function updateEmptyState() {
    var state = log.querySelector("[data-chat-state]");
    var hasMessages = !!log.querySelector(".msg");
    if (hasMessages && state) state.remove();
    if (!hasMessages) {
      if (!state) {
        state = document.createElement("p");
        state.className = "chat-state";
        state.dataset.chatState = "";
        log.appendChild(state);
      }
      state.textContent = S.empty;
    }
  }

  function scrollToBottom(force) {
    // 用户往上翻看旧消息时不强制滚到底
    var nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
    if (force || nearBottom) log.scrollTop = log.scrollHeight;
  }

  // live：这批消息是刚刚收到的（定时轮询）。页面首次加载、切回标签页时拿到的是"历史"，只记下不出声
  function addMessages(list, force, live) {
    list.forEach(function (m) {
      renderMessage(m);
      if (m.id > lastId) lastId = m.id;
      var key = "msg:" + m.id;
      if (live && !m.mine) sound.event("message_receive", key); // 同一条消息只响一次
      else sound.seen(key);
    });
    updateEmptyState();
    if (list.length) scrollToBottom(force);
  }

  // ---------- 和好 ----------

  var partnerWanted = null; // 上一次轮询时，对方是否已经按了和好
  function updateReconcile(state, live) {
    // 对方刚按了和好（这一轮和好只响一次，key 带上最近一次拥抱的 id）
    var key = "reconcile_invite:" + hugId;
    if (state.partner && !state.me && partnerWanted === false && live) sound.event("reconcile_invite", key);
    else if (state.partner) sound.seen(key);
    partnerWanted = !!state.partner;
    var status = $("[data-reconcile-status]");
    document.querySelectorAll("[data-reconcile]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", state.me ? "true" : "false");
    });
    var text = state.me ? S.reconcile_waiting : state.partner ? S.reconcile_partner : "";
    if (status) status.textContent = text;
    // 聊天区上方的小横幅：手机端没有左侧栏，"TA 想和好啦"和"等 TA 回应"都显示在这里
    var banner = $("[data-partner-banner]");
    banner.hidden = !text;
    banner.classList.toggle("is-mine", !!state.me);
    banner.querySelector("span").textContent = text;
  }

  // ---------- 心情（只显示用户自己选的心情，见 services/mood.py） ----------
  var moodKeys = ["happy", "wronged", "need_space", "calm"];

  function updateMoods(moods) {
    Object.keys(moods).forEach(function (who) {
      var m = moods[who];
      // 头像动作：开心挥爪、委屈垂耳、需要空间缩小
      document.querySelectorAll('[data-mood-of="' + who + '"]').forEach(function (el) {
        moodKeys.forEach(function (k) {
          el.classList.remove("mood-" + k);
        });
        el.classList.add("mood-" + m.key);
      });
      document.querySelectorAll('[data-mood-label="' + who + '"]').forEach(function (el) {
        moodKeys.forEach(function (k) {
          el.classList.remove("mood-pill-" + k);
        });
        el.classList.add("mood-pill-" + m.key);
        el.textContent = m.label;
        // 手机顶部只在对方心情不是"平静"时显示
        if (el.closest(".chat-head")) el.hidden = m.key === "calm";
      });
      if (who === "partner") {
        var hint = $("[data-mood-hint]");
        if (hint) {
          hint.textContent = m.hint || "";
          hint.hidden = m.key === "calm";
        }
      }
    });
  }

  function checkHug(newHugId) {
    if (newHugId > hugId) {
      hugId = newHugId;
      sound.event("reconcile_complete", "hug:" + newHugId); // 双方和好：不另播回忆保存音
      playHug();
    }
  }

  function playHug() {
    var overlay = $("[data-hug-overlay]");
    overlay.hidden = false;
    overlay.classList.remove("is-playing");
    void overlay.offsetWidth; // 重新播放动画
    overlay.classList.add("is-playing");
    var close = function () {
      overlay.hidden = true;
      overlay.classList.remove("is-playing");
    };
    overlay.onclick = close;
    setTimeout(close, reduceMotion ? 2500 : 3600);
  }

  document.querySelectorAll("[data-reconcile]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      api("/api/whisper/reconcile", {}).then(function (data) {
        if (data.reconcile) updateReconcile(data.reconcile);
        if (data.hug_id) checkHug(data.hug_id);
      });
    });
  });

  // ---------- 轮询 ----------

  // live：定时轮询（可以出声）；第一次加载和切回标签页时不补播
  function poll(force, live) {
    return api("/api/whisper/messages?after=" + lastId)
      .then(function (data) {
        addMessages(data.messages || [], force, live);
        updateReconcile(data.reconcile, live);
        if (data.moods) updateMoods(data.moods);
        checkHug(data.hug_id || 0);
      })
      .catch(function () {
        if (!log.querySelector(".msg")) {
          var state = log.querySelector("[data-chat-state]");
          if (state) state.textContent = S.load_failed;
        }
      });
  }

  function startPolling() {
    if (pollTimer) return;
    poll(true);
    pollTimer = setInterval(function () {
      if (!document.hidden) poll(false, true);
    }, 4000);
  }

  // 切回这个标签页时立刻拉一次
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && pollTimer) poll(false);
  });

  // ---------- 输入框 ----------

  function setError(msg) {
    composerError.textContent = msg || "";
  }

  input.addEventListener("input", function () {
    $("[data-char-count]").textContent = input.value.length + "/500";
    setError("");
  });

  input.addEventListener("keydown", function (event) {
    // 中文输入法正在选字时按的 Enter 不算发送
    if (event.isComposing || event.keyCode === 229) return;
    if (enterSends && event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      startSoften();
    }
  });

  function currentText() {
    var text = input.value.trim();
    if (!text) {
      setError(S.empty_input);
      input.focus();
      return null;
    }
    if (text.length > 500) {
      setError(S.too_long);
      return null;
    }
    return text;
  }

  // 发送（直接发送 / 软化版 / 改过的版本）
  function send(text, original) {
    if (busy) return Promise.resolve();
    busy = true;
    return api("/api/whisper/send", { text: text, original: original || null })
      .then(function (data) {
        if (!data.message) throw new Error(data.message || "send_failed");
        input.value = "";
        $("[data-char-count]").textContent = "0/500";
        setError("");
        addMessages([data.message], true);
        sound.play("message_send");
        playSendFlight();
        if (dlgPreview.open) dlgPreview.close();
      })
      .catch(function () {
        setError(S.send_failed);
        sound.play("ui_error");
        if (dlgPreview.open) dlgPreview.close();
      })
      .finally(function () {
        busy = false;
      });
  }

  // 送信小动画：不阻塞发送，也不延迟消息显示
  function playSendFlight() {
    if (reduceMotion) return;
    var flight = $("[data-send-flight]");
    flight.classList.remove("is-flying");
    void flight.offsetWidth;
    flight.classList.add("is-flying");
  }

  $("[data-direct]").addEventListener("click", function () {
    var text = currentText();
    if (text) send(text, null);
  });

  composer.addEventListener("submit", function (event) {
    event.preventDefault();
    startSoften();
  });

  // ---------- 温柔转达 ----------

  var pendingOriginal = "";
  var pendingSoftened = "";

  function startSoften() {
    if (busy || needsKey) return;
    var text = currentText();
    if (!text) return;
    busy = true;
    pendingOriginal = text;
    showStep("loading");
    openDialog(dlgPreview);

    api("/api/whisper/soften", { text: text })
      .then(function (data) {
        busy = false;
        if (data.status === "ok") {
          pendingSoftened = data.softened;
          $("[data-preview-original]").textContent = pendingOriginal;
          $("[data-preview-softened]").textContent = pendingSoftened;
          showStep("result");
          sound.play("draft_ready"); // 草稿好了（还没有发送）
          $("[data-preview-send]").focus();
        } else if (data.status === "unsafe") {
          // 不发送、不显示改写，换成安全卡片
          dlgPreview.close();
          openDialog(dlgSafety);
        } else if (data.status === "need_key" || data.code === "key_invalid_now") {
          dlgPreview.close();
          if (data.message) setKeyMessage(data.message, true);
          openDialog(dlgKey);
        } else {
          $("[data-preview-error]").textContent = data.message || S["errors.error"];
          showStep("error");
          sound.play("ui_error");
        }
      })
      .catch(function () {
        busy = false;
        $("[data-preview-error]").textContent = S["errors.network"];
        showStep("error");
        sound.play("ui_error");
      });
  }

  $("[data-preview-send]").addEventListener("click", function () {
    send(pendingSoftened, pendingOriginal);
  });

  $("[data-preview-edit]").addEventListener("click", function () {
    var edit = $("[data-preview-edit-input]");
    edit.value = pendingSoftened;
    showStep("edit");
    edit.focus();
  });

  $("[data-preview-back]").addEventListener("click", function () {
    showStep("result");
  });

  $("[data-preview-send-edited]").addEventListener("click", function () {
    var edited = $("[data-preview-edit-input]").value.trim();
    if (edited) send(edited, pendingOriginal);
  });

  $("[data-preview-cancel]").addEventListener("click", function () {
    sound.play("ui_close");
    dlgPreview.close(); // 原话留在输入框里，可以继续改
  });

  $("[data-preview-close]").addEventListener("click", function () {
    sound.play("ui_close");
    dlgPreview.close();
  });

  // 等待中不允许按 Esc 关掉弹窗（请求还在进行）
  dlgPreview.addEventListener("cancel", function (event) {
    if (busy) event.preventDefault();
  });

  // ---------- API key 弹窗 ----------

  var keyForm = $("[data-key-form]");
  var keyInput = $("[data-key-input]");
  var keyMessage = $("[data-key-message]");
  var keySubmit = $("[data-key-submit]");

  function setKeyMessage(msg, isError) {
    keyMessage.textContent = msg || "";
    keyMessage.classList.toggle("is-error", !!isError);
    keyMessage.classList.toggle("is-success", !!msg && !isError);
  }

  $("[data-key-toggle]").addEventListener("click", function (event) {
    var show = keyInput.type === "password";
    keyInput.type = show ? "text" : "password";
    event.currentTarget.textContent = show ? S["key.hide"] : S["key.show"];
  });

  keyForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var key = keyInput.value.trim();
    if (key.length < 10 || /\s/.test(key)) {
      setKeyMessage(S["key.format"], true);
      return;
    }
    keySubmit.disabled = true;
    setKeyMessage(S["key.testing"], false);
    api("/api/whisper/key", { api_key: key })
      .then(function (data) {
        if (!data.ok) {
          setKeyMessage(data.message, true);
          return;
        }
        setKeyMessage(data.message, false); // 魔法已点亮！
        keyInput.value = ""; // 不在页面上留着 key
        $("[data-masked-key]").textContent = data.masked;
        $("[data-key-status]").hidden = false;
        needsKey = false;
        $("[data-need-key]").hidden = true;
        composer.hidden = false;
        setTimeout(function () {
          dlgKey.close();
          setKeyMessage("");
          input.focus();
        }, 900);
        startPolling();
      })
      .catch(function () {
        setKeyMessage(S["errors.network"], true);
      })
      .finally(function () {
        keySubmit.disabled = false;
      });
  });

  $("[data-open-key]").addEventListener("click", function () {
    openDialog(dlgKey);
  });

  // ---------- 键盘弹起时保持输入框可见 ----------
  // iPhone 上键盘弹起后 100dvh 不会变小，用 visualViewport 的真实可见高度
  if (window.visualViewport) {
    var setHeight = function () {
      document.documentElement.style.setProperty("--vvh", window.visualViewport.height + "px");
    };
    window.visualViewport.addEventListener("resize", setHeight);
    setHeight();
  }

  // ---------- 开始 ----------
  // 轮询只是读取（消息、和好、心情），没有 key 也照常进行；key 只决定能不能发送
  if (needsKey) {
    openDialog(dlgKey); // 首次进入传话码头：弹出"点亮传话魔法"
  }
  startPolling();
})();
