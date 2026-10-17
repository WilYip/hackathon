// Usland 全站声音管理器（所有页面都通过它播放声音，不要在别处 new Audio）
//
// 三类声音（清单在 content/audio_manifest.json，由 base.html 输出到 #sound-manifest）：
//   bgm      背景音乐：每页一首（<body data-bgm>），循环时约 2 秒交叉淡化
//   ambience 环境声：每页一个循环环境声（data-amb）+ 偶尔的环境音效（data-amb-extra，例如风声、鸟鸣）
//   sfx      音效：页面脚本调用 UslandSound.play("ui_select") 等
//
// 规则：
// - 声音默认关闭。用户点了开关（首页 / 小信箱）之后才加载背景音乐和环境声；偏好存在 localStorage
// - 多页面网站：换页时把背景音乐的位置存在 sessionStorage，新页面从同一位置继续并淡入；
//   换成另一首时，新页面先接着播旧的那首，再用约 2 秒交叉淡化到新的一首
// - 标签页切到后台时暂停音乐和环境声，切回来再淡入
// - 事件音按"事件 key"去重（localStorage 记住播过的 key）：同一条消息、同一次和好只响一次；
//   页面首次加载、刷新、轮询拿到的历史事件只记下 key，不补播
// - 任何加载或播放失败都静默跳过：这里的每个入口都包了 try/catch，绝不影响聊天、保存等功能
(function () {
  "use strict";

  var PREF_KEY = "usland_sound_prefs"; // localStorage：开关和音量
  var SEEN_KEY = "usland_sound_seen"; // localStorage：已经播过（或已经算作历史）的事件 key
  var STATE_KEY = "usland_sound_state"; // sessionStorage：背景音乐 / 环境声现在播到哪里
  var LIVE_KEY = "usland_sound_live"; // sessionStorage：下一个页面是"刚刚发生的变化"（提交表单 / 轮询刷新）
  var NEXT_KEY = "usland_sound_next"; // sessionStorage：下一个页面要播的音效
  var LAST_KEY = "usland_sound_last"; // sessionStorage：上一个页面的区域、最近播过的音效（防止重复）

  var DEFAULTS = {
    enabled: false, // 总开关：默认关闭
    bgm: true,
    amb: true,
    sfx: true,
    error: false, // 出错提示音：默认不响（出错时已经有文字提示）
    volume: { bgm: 1, amb: 1, sfx: 1 }, // 在建议音量基础上再乘的比例（0–1）
  };
  var CAT = { bgm: "bgm", ambience: "amb", sfx: "sfx" }; // 清单里的类别 → 偏好里的名字
  var BGM_FADE = 2000; // 换歌时交叉淡化（毫秒）
  var RESUME_FADE = 900; // 换页 / 切回标签页时淡入
  var STATE_FRESH = 20000; // 保存的播放位置多久内有效（换页一般几百毫秒）
  var MINOR = { ui_select: 1, ui_close: 1 }; // 小音效：紧跟在别的音效后面时省略，一次操作只突出一个声音

  var noop = function () {};
  var safe = function (fn) {
    return function () {
      try {
        return fn.apply(this, arguments);
      } catch (e) {
        return undefined; // 声音出错不影响页面
      }
    };
  };

  // ---------- 存储（隐私模式等情况下可能不能用，全部容错） ----------
  function load(store, key, fallback) {
    try {
      var raw = window[store].getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }
  function save(store, key, value) {
    try {
      if (value === null) window[store].removeItem(key);
      else window[store].setItem(key, JSON.stringify(value));
    } catch (e) {
      // 存不了就算了
    }
  }

  function readPrefs() {
    var p = load("localStorage", PREF_KEY, {}) || {};
    var prefs = {};
    Object.keys(DEFAULTS).forEach(function (k) {
      prefs[k] = k in p ? p[k] : DEFAULTS[k];
    });
    prefs.volume = {};
    ["bgm", "amb", "sfx"].forEach(function (k) {
      var v = p.volume && typeof p.volume[k] === "number" ? p.volume[k] : DEFAULTS.volume[k];
      prefs.volume[k] = Math.max(0, Math.min(1, v));
    });
    return prefs;
  }

  var prefs = readPrefs();
  var manifest = {};
  try {
    manifest = JSON.parse(document.getElementById("sound-manifest").textContent) || {};
  } catch (e) {
    manifest = {};
  }
  var body = document.body;
  var scene = {
    bgm: body.dataset.bgm || "",
    bgmGain: parseFloat(body.dataset.bgmGain) || 1,
    amb: body.dataset.amb || "",
    ambExtra: body.dataset.ambExtra || "",
    region: body.dataset.soundRegion || "",
    enter: body.dataset.soundEnter || "",
  };

  // ---------- 播放引擎：有 Web Audio 时用增益节点控制音量（手机 Safari 不能直接改 audio.volume） ----------
  var ctx = null;
  function getCtx() {
    if (ctx) return ctx;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      ctx = new AC();
    } catch (e) {
      ctx = null;
    }
    return ctx;
  }

  // 浏览器要求"用户操作后才能出声"。换页后通常可以直接播放；不行的话，等用户下一次点击 / 按键
  var waiting = [];
  function unlocked() {
    var c = getCtx();
    return !c || c.state === "running";
  }
  function whenUnlocked(fn) {
    if (unlocked()) return fn();
    waiting.push(fn);
    tryUnlock();
  }
  function flush() {
    var list = waiting;
    waiting = [];
    list.forEach(function (fn) {
      safe(fn)();
    });
  }
  function tryUnlock() {
    if (!prefs.enabled) return; // 声音关着：什么都不做（也不创建音频环境）
    var c = getCtx();
    if (!c) return flush();
    if (c.state === "running") return flush();
    try {
      c.resume().then(function () {
        if (c.state === "running") flush();
      }, noop);
    } catch (e) {
      // 忽略
    }
  }
  ["pointerdown", "keydown", "touchend"].forEach(function (type) {
    document.addEventListener(type, safe(tryUnlock), { capture: true, passive: true });
  });

  // 一个"声部"：一个 <audio> 元素 + 自己的音量。mix 是淡入淡出的系数（0–1）
  function Voice(asset, levelFn) {
    var el = new Audio();
    el.preload = "auto";
    el.src = asset.src;
    this.el = el;
    this.gain = null;
    this.mix = 0;
    this.levelFn = levelFn;
    this.dur = asset.dur || 0; // 时长来自清单，不用等文件加载
    this.failed = false;
    var self = this;
    el.addEventListener("error", function () {
      self.failed = true; // 文件加载失败：静默放弃
    });
    // 自己记"已经开始出声"：离开页面时浏览器会先把 audio 暂停，不能用 el.paused 判断
    el.addEventListener("playing", function () {
      self.started = true;
    });
    var c = getCtx();
    if (c) {
      try {
        var node = c.createMediaElementSource(el);
        this.gain = c.createGain();
        this.gain.gain.value = 0;
        node.connect(this.gain);
        this.gain.connect(c.destination);
      } catch (e) {
        this.gain = null;
      }
    }
    this.apply();
  }
  Voice.prototype.apply = function () {
    var level = Math.max(0, Math.min(1, this.levelFn() * this.mix));
    try {
      if (this.gain) this.gain.gain.value = level;
      else this.el.volume = level;
    } catch (e) {
      // 忽略
    }
  };
  // position：从第几秒开始（数字，或者返回数字的函数）。
  // 文件还没加载时也可以直接设置 currentTime，浏览器会在加载好后从这个位置开始。
  // onStart：真正开始出声时调用（淡入从这时开始，不然加载慢时淡入在静音中就做完了）
  Voice.prototype.play = function (position, onStart) {
    var el = this.el;
    var self = this;
    try {
      var at = typeof position === "function" ? position() : position;
      var dur = this.dur;
      if (at && dur) at = at % dur;
      if (at) el.currentTime = at;
    } catch (e) {
      // 定位失败就从头放
    }
    if (onStart) el.addEventListener("playing", safe(onStart), { once: true });
    var p = el.play();
    if (p && p.catch) {
      p.catch(function () {
        // 还没解锁：等用户下一次操作再试
        if (!self.failed && !self.stopped) waiting.push(function () {
          if (!self.stopped) el.play().catch(noop);
        });
      });
    }
  };
  Voice.prototype.stop = function () {
    this.stopped = true;
    try {
      this.el.pause();
      this.el.removeAttribute("src");
      this.el.load(); // 释放文件
    } catch (e) {
      // 忽略
    }
  };

  // ---------- 淡入淡出 ----------
  var fades = [];
  var fadeTimer = null;
  function fade(voice, to, ms, done) {
    fades = fades.filter(function (f) {
      return f.voice !== voice;
    });
    if (!ms) {
      voice.mix = to;
      voice.apply();
      if (done) done();
      return;
    }
    fades.push({ voice: voice, from: voice.mix, to: to, start: Date.now(), ms: ms, done: done });
    if (!fadeTimer) fadeTimer = setInterval(safe(tickFades), 40);
  }
  function tickFades() {
    var now = Date.now();
    var finished = [];
    fades.forEach(function (f) {
      var k = Math.min(1, (now - f.start) / f.ms);
      f.voice.mix = f.from + (f.to - f.from) * k;
      f.voice.apply();
      if (k >= 1) finished.push(f);
    });
    fades = fades.filter(function (f) {
      return finished.indexOf(f) === -1;
    });
    finished.forEach(function (f) {
      if (f.done) safe(f.done)();
    });
    if (!fades.length) {
      clearInterval(fadeTimer);
      fadeTimer = null;
    }
  }

  // ---------- 一条循环音轨（背景音乐或环境声） ----------
  // 循环时：快到结尾就从头再开一个声部，交叉淡化（避免生硬的接缝）
  function Track(kind, id, gain) {
    this.kind = kind; // "bgm" 或 "amb"
    this.id = id;
    this.asset = manifest[id];
    this.gain = gain || 1;
    this.voices = [];
    this.current = null;
    this.paused = false;
    var a = this.asset;
    this.xfade = ((a && a.xfade) || (kind === "bgm" ? 2 : 1)) * 1000;
  }
  Track.prototype.level = function () {
    return this.asset.vol * prefs.volume[this.kind] * this.gain;
  };
  Track.prototype.start = function (position, fadeMs) {
    if (!this.asset) return;
    var self = this;
    var v = new Voice(this.asset, function () {
      return self.level();
    });
    // 很短的循环素材直接用 loop；长的自己做交叉淡化
    var dur = this.asset.dur || 0;
    v.el.loop = this.asset.loop && dur < (this.xfade / 1000) * 3;
    v.el.addEventListener("ended", function () {
      if (self.current === v && !self.asset.loop) self.current = null;
    });
    this.voices.push(v);
    this.current = v;
    whenUnlocked(function () {
      if (v.stopped) return; // 等解锁期间已经被停掉了
      v.play(position || 0, function () {
        if (!v.stopped) fade(v, 1, fadeMs || 0);
      });
    });
  };
  Track.prototype.position = function () {
    try {
      return this.current ? this.current.el.currentTime : 0;
    } catch (e) {
      return 0;
    }
  };
  // 是否正在放（因为标签页到后台而暂停的也算：离开页面时浏览器会先触发"切到后台"）
  Track.prototype.isPlaying = function () {
    return !!(this.current && (!this.paused || this.hiddenPause) && !this.current.failed && this.current.started);
  };
  // 每 250ms 检查一次：快到结尾就交叉淡化到新的一遍
  Track.prototype.tick = function () {
    var v = this.current;
    if (!v || this.paused || !this.asset.loop || v.el.loop || v.looping) return;
    var el = v.el;
    if (!isFinite(el.duration) || el.duration <= 0) return;
    if (el.duration - el.currentTime <= this.xfade / 1000) {
      v.looping = true;
      var self = this;
      var old = v;
      this.start(0, this.xfade);
      fade(old, 0, this.xfade, function () {
        old.stop();
        self.voices = self.voices.filter(function (x) {
          return x !== old;
        });
      });
    }
  };
  Track.prototype.stop = function (ms) {
    var list = this.voices;
    this.voices = [];
    this.current = null;
    list.forEach(function (v) {
      fade(v, 0, ms || 0, function () {
        v.stop();
      });
    });
  };
  Track.prototype.pause = function (ms) {
    this.paused = true;
    this.voices.forEach(function (v) {
      fade(v, 0, ms || 0, function () {
        try {
          v.el.pause();
        } catch (e) {
          // 忽略
        }
      });
    });
  };
  Track.prototype.resume = function (ms) {
    if (!this.paused) return;
    this.paused = false;
    var v = this.current;
    if (!v) return;
    whenUnlocked(function () {
      v.el.play().catch(noop);
      fade(v, 1, ms || 0);
    });
  };
  Track.prototype.refresh = function () {
    this.voices.forEach(function (v) {
      v.apply();
    });
  };

  var tracks = { bgm: null, amb: null };
  var ghosts = []; // 换页交叉淡化时临时播放的上一首

  function wanted(kind) {
    if (!prefs.enabled || !prefs[kind]) return "";
    var id = kind === "bgm" ? scene.bgm : scene.amb;
    return manifest[id] ? id : "";
  }

  // 按当前页面的场景开始（或停止）背景音乐 / 环境声。
  // continueFrom：上一个页面留下的播放位置（换页时用）
  function startKind(kind, continueFrom) {
    var id = wanted(kind);
    var gain = kind === "bgm" ? scene.bgmGain : 1;
    var cur = tracks[kind];
    if (cur && cur.id === id) return; // 已经在放这首
    if (cur) {
      cur.stop(kind === "bgm" ? BGM_FADE : 1000);
      tracks[kind] = null;
    }
    if (!id) return;
    var track = new Track(kind, id, gain);
    tracks[kind] = track;
    var saved = continueFrom && continueFrom[kind];
    if (saved && saved.playing && Date.now() - saved.at < STATE_FRESH && manifest[saved.id]) {
      // 真正开始播放时再算位置：加上换页（和等待解锁）花掉的时间
      var pos = function () {
        return saved.pos + (Date.now() - saved.at) / 1000;
      };
      if (saved.id === id) {
        track.start(pos, RESUME_FADE); // 同一首：从同一位置继续，淡入
        return;
      }
      if (!unlocked()) {
        track.start(0, kind === "bgm" ? 1500 : 1000); // 还不能出声：上一首没法接着放，直接淡入新的
        return;
      }
      // 换了一首：先接着放上一首，再交叉淡化
      var ms = kind === "bgm" ? BGM_FADE : 1000;
      var ghost = new Track(kind, saved.id, saved.gain || 1);
      ghost.start(pos, 0);
      ghosts.push(ghost);
      // 上一首真正响起来以后再开始淡出；3 秒还没响（加载慢）就直接放弃
      var fadeGhost = safe(function () {
        if (ghost.current) ghost.stop(ms);
        ghosts = ghosts.filter(function (g) {
          return g !== ghost;
        });
      });
      if (ghost.current) ghost.current.el.addEventListener("playing", fadeGhost, { once: true });
      setTimeout(fadeGhost, 3000);
      track.start(0, ms);
      return;
    }
    track.start(0, kind === "bgm" ? 1500 : 1000);
  }

  function startScene(continueFrom) {
    startKind("bgm", continueFrom);
    startKind("amb", continueFrom);
    scheduleExtra();
  }

  function stopAll(ms) {
    ["bgm", "amb"].forEach(function (kind) {
      if (tracks[kind]) tracks[kind].stop(ms);
      tracks[kind] = null;
    });
    ghosts.forEach(function (g) {
      g.stop(ms);
    });
    ghosts = [];
    save("sessionStorage", STATE_KEY, null);
  }

  // 记下现在播到哪里（换页后用）
  function saveState() {
    var state = {};
    ["bgm", "amb"].forEach(function (kind) {
      var t = tracks[kind];
      if (t && t.current) {
        state[kind] = { id: t.id, pos: t.position(), at: Date.now(), playing: t.isPlaying(), gain: t.gain };
      }
    });
    save("sessionStorage", STATE_KEY, state);
  }

  setInterval(
    safe(function () {
      ["bgm", "amb"].forEach(function (kind) {
        if (tracks[kind]) tracks[kind].tick();
      });
      ghosts.forEach(function (g) {
        g.tick();
      });
    }),
    250
  );
  setInterval(safe(saveState), 1000);
  window.addEventListener("pagehide", safe(saveState));

  // ---------- 偶尔的环境音效（风声、鸟鸣、船轻轻晃）：每隔 40–90 秒响一次 ----------
  var extraTimer = null;
  function scheduleExtra() {
    clearTimeout(extraTimer);
    if (!scene.ambExtra || !manifest[scene.ambExtra]) return;
    extraTimer = setTimeout(
      safe(function () {
        if (prefs.enabled && prefs.amb && !document.hidden) oneShot(scene.ambExtra, "amb");
        scheduleExtra();
      }),
      40000 + Math.random() * 50000
    );
  }

  // ---------- 音效 ----------
  var buffers = {}; // id → Promise<AudioBuffer 或 null>
  function loadBuffer(id) {
    var c = getCtx();
    if (!c || !window.fetch) return null;
    if (!buffers[id]) {
      buffers[id] = fetch(manifest[id].src)
        .then(function (r) {
          if (!r.ok) throw new Error("load");
          return r.arrayBuffer();
        })
        .then(function (data) {
          return new Promise(function (resolve) {
            // 旧版 Safari 只支持回调写法
            var p = c.decodeAudioData(data, resolve, function () {
              resolve(null);
            });
            if (p && p.catch) p.catch(function () {
              resolve(null);
            });
          });
        })
        .catch(function () {
          return null;
        });
    }
    return buffers[id];
  }

  // 播放一个短声音（kind：sfx 或 amb）
  function oneShot(id, kind) {
    var asset = manifest[id];
    if (!asset) return;
    var level = asset.vol * prefs.volume[kind];
    var c = getCtx();
    var promise = loadBuffer(id);
    if (c && promise) {
      promise.then(
        safe(function (buffer) {
          if (!buffer) return;
          whenUnlocked(function () {
            var src = c.createBufferSource();
            var g = c.createGain();
            g.gain.value = level;
            src.buffer = buffer;
            src.connect(g);
            g.connect(c.destination);
            src.start();
          });
        })
      );
      return;
    }
    var el = new Audio(asset.src);
    el.volume = Math.max(0, Math.min(1, level));
    var p = el.play();
    if (p && p.catch) p.catch(noop);
  }

  var lastSfxAt = 0;
  function play(id) {
    if (!prefs.enabled || !prefs.sfx || !manifest[id]) return false;
    if (manifest[id].cat !== "sfx") return false;
    if (id === "ui_error" && !prefs.error) return false;
    var now = Date.now();
    if (MINOR[id] && now - lastSfxAt < 250) return false; // 一次操作只突出一个声音
    // 同一个音效 1.5 秒内不重复（例如点信箱面板后马上进入设置页）
    var last = load("sessionStorage", LAST_KEY, {}) || {};
    if (last.sfx === id && now - last.sfxAt < 1500) return false;
    last.sfx = id;
    last.sfxAt = now;
    save("sessionStorage", LAST_KEY, last);
    lastSfxAt = now;
    oneShot(id, "sfx");
    return true;
  }

  // ---------- 事件去重 ----------
  var seenList = load("localStorage", SEEN_KEY, []) || [];
  function seen(key) {
    return seenList.indexOf(key) !== -1;
  }
  function markSeen(key) {
    if (!key || seen(key)) return;
    seenList.push(key);
    if (seenList.length > 300) seenList = seenList.slice(-300);
    save("localStorage", SEEN_KEY, seenList);
  }
  // 同一个事件只播一次（其他标签页播过也算）
  function event(id, key) {
    if (!key) return play(id);
    seenList = load("localStorage", SEEN_KEY, seenList) || seenList; // 读最新的（可能别的标签页刚写过）
    if (seen(key)) return false;
    markSeen(key);
    return play(id);
  }

  // ---------- 开关 ----------
  function setPrefs(changes) {
    var wasEnabled = prefs.enabled;
    Object.keys(changes).forEach(function (k) {
      if (k === "volume") {
        Object.keys(changes.volume).forEach(function (v) {
          prefs.volume[v] = Math.max(0, Math.min(1, changes.volume[v]));
        });
      } else {
        prefs[k] = changes[k];
      }
    });
    save("localStorage", PREF_KEY, prefs);
    if (!prefs.enabled) {
      stopAll(400);
      clearTimeout(extraTimer);
    } else {
      if (!wasEnabled) tryUnlock(); // 这次点击就是用户操作，可以直接出声
      startScene(null);
      ["bgm", "amb"].forEach(function (kind) {
        if (tracks[kind]) tracks[kind].refresh();
      });
      if (prefs.sfx) preloadSfx();
    }
    updateControls();
  }

  // 开启声音后，空闲时把所有音效先下载好（都很小），点击时就不会慢半拍
  var preloaded = false;
  function preloadSfx() {
    if (preloaded || !getCtx()) return;
    preloaded = true;
    var run = function () {
      Object.keys(manifest).forEach(function (id) {
        if (manifest[id].cat === "sfx") loadBuffer(id);
      });
    };
    if (window.requestIdleCallback) window.requestIdleCallback(run);
    else setTimeout(run, 1500);
  }

  // 页面上的开关和滑块：
  //   [data-sound-toggle]          总开关按钮（首页、小信箱）
  //   [data-sound-pref="bgm"]      复选框：bgm / amb / sfx / error
  //   [data-sound-volume="bgm"]    滑块 0–100：bgm / amb / sfx
  function updateControls() {
    document.querySelectorAll("[data-sound-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", prefs.enabled ? "true" : "false");
      btn.classList.toggle("is-on", prefs.enabled);
      var label = btn.querySelector("[data-sound-label]");
      if (label) label.textContent = prefs.enabled ? btn.dataset.labelOn : btn.dataset.labelOff;
      if (btn.dataset.titleOn) btn.title = prefs.enabled ? btn.dataset.titleOn : btn.dataset.titleOff;
    });
    document.querySelectorAll("[data-sound-pref]").forEach(function (input) {
      input.checked = !!prefs[input.dataset.soundPref];
    });
    document.querySelectorAll("[data-sound-volume]").forEach(function (input) {
      input.value = Math.round(prefs.volume[input.dataset.soundVolume] * 100);
    });
    document.querySelectorAll("[data-sound-details]").forEach(function (box) {
      box.classList.toggle("is-off", !prefs.enabled);
    });
  }

  function bindControls() {
    document.querySelectorAll("[data-sound-toggle]").forEach(function (btn) {
      btn.hidden = false; // 没有 JavaScript 时开关一直隐藏（反正也放不了声音）
      btn.addEventListener(
        "click",
        safe(function () {
          setPrefs({ enabled: !prefs.enabled });
          if (prefs.enabled) play("ui_select");
        })
      );
    });
    document.querySelectorAll("[data-sound-pref]").forEach(function (input) {
      input.addEventListener(
        "change",
        safe(function () {
          var change = {};
          change[input.dataset.soundPref] = input.checked;
          setPrefs(change);
        })
      );
    });
    document.querySelectorAll("[data-sound-volume]").forEach(function (input) {
      input.addEventListener(
        "input",
        safe(function () {
          var change = { volume: {} };
          change.volume[input.dataset.soundVolume] = Number(input.value) / 100;
          setPrefs(change);
        })
      );
    });
    updateControls();
  }

  // ---------- 全站通用的操作音 ----------
  // 选答案、选条件、开关 → ui_select；关闭面板、取消 → ui_close；退出登录 → 音乐淡出
  function bindCommon() {
    document.addEventListener(
      "change",
      safe(function (e) {
        var t = e.target;
        if (!e.isTrusted || !t || (t.type !== "radio" && t.type !== "checkbox")) return;
        if (t.closest("[data-sound-quiet]")) return;
        play("ui_select");
      }),
      true
    );
    document.addEventListener(
      "click",
      safe(function (e) {
        var t = e.target && e.target.closest ? e.target.closest(".panel-close, [data-sound-close]") : null;
        if (t) play("ui_close");
      }),
      true
    );
    // Esc 关闭弹窗
    document.querySelectorAll("dialog").forEach(function (d) {
      d.addEventListener(
        "cancel",
        safe(function () {
          play("ui_close");
        })
      );
    });
    document.addEventListener(
      "submit",
      safe(function (e) {
        var form = e.target;
        var action = form.getAttribute("action") || "";
        // 退出登录：音乐淡出后再提交（声音关闭时直接提交）
        if (/\/logout$/.test(action) && (tracks.bgm || tracks.amb) && !form.dataset.soundFaded) {
          e.preventDefault();
          form.dataset.soundFaded = "1";
          stopAll(600);
          setTimeout(function () {
            form.submit();
          }, 650);
          return;
        }
        // 自己提交的表单：下一个页面上的变化是"刚刚发生的"，可以播放对应的事件音
        expectLive();
      })
    );
  }

  function expectLive() {
    save("sessionStorage", LIVE_KEY, Date.now());
  }

  // ---------- 页面加载时 ----------
  function onLoad() {
    var live = load("sessionStorage", LIVE_KEY, 0);
    save("sessionStorage", LIVE_KEY, null);
    var isLive = live && Date.now() - live < STATE_FRESH;

    // 1. 背景音乐 / 环境声：接着上一个页面
    var state = load("sessionStorage", STATE_KEY, null);
    if (prefs.enabled) {
      // 先试着解锁（换页后浏览器通常允许直接出声）；最多等 0.4 秒，不行就先排队，等用户点一下再出声
      var started = false;
      var go = function () {
        if (started) return;
        started = true;
        startScene(state);
      };
      whenUnlocked(go);
      setTimeout(safe(go), 400);
      if (prefs.sfx) preloadSfx();
    }

    // 2. 进入新的区域（从别的区域点进来；刷新不算）
    var nav = performance.getEntriesByType ? performance.getEntriesByType("navigation")[0] : null;
    var navType = nav ? nav.type : "navigate";
    var last = load("sessionStorage", LAST_KEY, {}) || {};
    if (scene.enter && navType !== "reload" && last.region && last.region !== scene.region) {
      play(scene.enter);
    }
    last = load("sessionStorage", LAST_KEY, {}) || {};
    last.region = scene.region;
    save("sessionStorage", LAST_KEY, last);

    // 3. 服务器说"你刚完成的操作"要响一下（保存成功、登录成功……，见 services/sound.py）
    try {
      JSON.parse(document.getElementById("sound-cues").textContent).forEach(function (id) {
        play(id);
      });
    } catch (e) {
      // 忽略
    }

    // 4. 上一个页面交代"到下一个页面再响"的音效（例如另一半加入后跳到首页）
    var next = load("sessionStorage", NEXT_KEY, []) || [];
    save("sessionStorage", NEXT_KEY, null);
    next.forEach(function (n) {
      if (Date.now() - n.at < STATE_FRESH) event(n.id, n.key);
    });

    // 5. 页面状态里的事件（约会任务推荐出来了、双方同意了……）：
    //    只有"刚刚发生的"才响（自己提交了表单、轮询发现变化后刷新，或者服务器标记为 fresh）；
    //    否则只记下 key，以后也不补播。一个页面最多响一个（列表按重要程度排好）
    var box = document.getElementById("sound-events");
    if (box) {
      try {
        var played = false;
        JSON.parse(box.textContent).forEach(function (ev) {
          if ((isLive || ev.fresh) && !played) played = event(ev.sound, ev.key);
          else markSeen(ev.key);
        });
      } catch (e) {
        // 忽略
      }
    }
  }

  // 标签页切到后台：暂停音乐和环境声；切回来再淡入
  document.addEventListener(
    "visibilitychange",
    safe(function () {
      ["bgm", "amb"].forEach(function (kind) {
        var t = tracks[kind];
        if (!t) return;
        if (document.hidden) {
          t.pause(250);
          t.hiddenPause = true;
        } else {
          t.hiddenPause = false;
          t.resume(RESUME_FADE);
        }
      });
      if (document.hidden) saveState();
    })
  );

  // ---------- 对外的接口：window.UslandSound ----------
  window.UslandSound = {
    // 播放一个音效，例如 UslandSound.play("message_send")
    play: safe(play),
    // 事件音：同一个 key 只响一次，例如 UslandSound.event("message_receive", "msg:42")
    event: safe(event),
    // 把事件记为"已经知道了"，不播放（页面首次加载、轮询拿到的历史事件）
    seen: safe(markSeen),
    // 到下一个页面再播（马上就要跳转时用）
    next: safe(function (id, key) {
      var list = load("sessionStorage", NEXT_KEY, []) || [];
      list.push({ id: id, key: key || null, at: Date.now() });
      save("sessionStorage", NEXT_KEY, list);
    }),
    // 页面马上要因为"状态变了"而刷新：新页面上的事件音可以播放
    expectLive: safe(expectLive),
    isEnabled: function () {
      return !!prefs.enabled;
    },
    // 查看现在在放什么（调试 / 验收用）：{enabled, bgm: {id, pos, playing, level}, amb: {...}, ctx}
    state: safe(function () {
      var out = { enabled: prefs.enabled, prefs: prefs, ctx: ctx ? ctx.state : "none", ghosts: ghosts.length };
      ["bgm", "amb"].forEach(function (kind) {
        var t = tracks[kind];
        out[kind] = t
          ? { id: t.id, pos: Math.round(t.position() * 10) / 10, playing: t.isPlaying(), voices: t.voices.length,
              mix: t.current ? Math.round(t.current.mix * 100) / 100 : 0 }
          : null;
      });
      return out;
    }),
  };

  safe(bindControls)();
  safe(bindCommon)();
  safe(onLoad)();
})();
