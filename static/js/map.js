// 小岛首页的交互（第三版素材）：
// - 5 秒循环视频：两段视频交叉淡入淡出循环（藏住首尾接缝），上面盖高清小岛；只加载正在显示的那套构图
// - 悬停 / 键盘聚焦某个入口时，对应的场景元素（小船、信箱、小屋、告示牌、两个石台）四周亮起光圈，标签抬起
// - 点击时短暂的按压反馈（光圈变亮、标签下压），然后进入功能或打开面板
// - 动物点一下随机做动作；点自己的动物选择心情
// - 图片加载中 / 加载失败的状态
// - 新用户第一次进入：自动打开"先去初见森林"的引导窗口
(function () {
  var stages = document.querySelectorAll("[data-map-stage]");
  if (!stages.length) return;
  // 全站声音管理器（static/js/sound.js）；万一没加载，用什么都不做的替身
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop, next: noop, expectLive: noop };

  // 用户开启了"减少动态效果"时，点击后立即跳转，不等动画
  // （系统设置或小信箱里的"减少动态效果"，见 base.html 的 uslandReduceMotion）
  var reduceMotion = window.uslandReduceMotion ? window.uslandReduceMotion() : false;

  // 把同一个区域的所有元素（热区、标签、图层）加 / 去掉某个 class
  function setRegionClass(stage, regionId, className, on) {
    stage.querySelectorAll('[data-region="' + regionId + '"]').forEach(function (el) {
      el.classList.toggle(className, on);
    });
  }

  // 点击入口之后做什么：直接进入，或者打开面板
  function activate(link) {
    var regionId = link.dataset.region;
    if (link.dataset.action === "panel") {
      var dialog = document.getElementById("panel-" + regionId);
      if (dialog && dialog.showModal) {
        sound.play(regionId === "mailbox" ? "mailbox_open" : "board_open");
        dialog.showModal();
        return;
      }
    }
    window.location.href = link.href;
  }

  // ---------- 循环视频 ----------
  // 视频首尾几帧有跳动，所以不用 loop 属性：快放完时让另一段从 HEAD 秒开始，
  // 叠在上面淡入（FADE 秒），然后把下面那段停掉，两段轮流。
  var HEAD = 0.25; // 跳过开头的几帧
  var TAIL = 0.3; // 结尾留出的时间
  var FADE = 0.6; // 交叉淡入的时长（和 CSS 的 transition 一样）

  function startLoopVideo(box) {
    if (box.dataset.started) return;
    box.dataset.started = "1";
    var src = box.dataset.src;
    var make = function (preload) {
      var v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.setAttribute("playsinline", "");
      v.preload = preload; // 第二段先只读信息，轮到它时同一个文件已经在浏览器缓存里了
      v.src = src;
      box.appendChild(v);
      return v;
    };
    var cur = make("auto");
    var next = make("metadata");
    // 高清小岛（盖在视频上）：和视频一起开始下载，视频播放后由 CSS（.is-playing）显示
    var detail = box.querySelector(".scene-detail");
    if (detail) {
      detail.src = detail.dataset.src;
      box.appendChild(detail); // 放到两段视频后面，叠在最上层
    }
    var switching = false;

    var playFrom = function (v) {
      try {
        v.currentTime = HEAD;
      } catch (e) {
        // 还没加载好时设置时间可能失败，从头播放也没关系
      }
      var p = v.play();
      return p && p.catch ? p : Promise.resolve();
    };

    var onTime = function () {
      if (this !== cur || switching || !cur.duration) return;
      if (cur.currentTime < cur.duration - TAIL - FADE) return;
      switching = true;
      var old = cur;
      next.style.zIndex = 2; // 新的一段盖在上面淡入
      old.style.zIndex = 1;
      playFrom(next).then(function () {
        next.classList.add("is-on");
        setTimeout(function () {
          old.classList.remove("is-on"); // 已经被盖住了，直接藏起来
          old.pause();
          cur = next;
          next = old;
          switching = false;
        }, FADE * 1000);
      }, function () {
        switching = false;
      });
    };
    cur.addEventListener("timeupdate", onTime);
    next.addEventListener("timeupdate", onTime);

    // 第一段：能播放了才显示（之前看到的是同一构图的静态底图）
    playFrom(cur).then(function () {
      cur.classList.add("is-on");
      box.classList.add("is-playing");
    }, function () {
      // 浏览器不允许自动播放：保持静态底图
    });

    // 暂停 / 继续：标签页到后台、或者这套构图被隐藏（窗口宽度跨过 700px）时暂停，省电
    var sync = function () {
      var shouldPlay = !document.hidden && box.offsetParent !== null;
      if (!shouldPlay) {
        cur.pause();
      } else if (cur.classList.contains("is-on") && cur.paused) {
        cur.play().catch(function () {});
      }
    };
    box.syncLoopVideo = sync;
    document.addEventListener("visibilitychange", sync);
  }

  // 只给正在显示的那套构图加载视频；窗口宽度跨过 700px 时另一套构图出现，再给它加载，
  // 被隐藏的那套暂停
  function startVisibleVideos() {
    if (reduceMotion) return;
    document.querySelectorAll("[data-scene-video]").forEach(function (box) {
      if (box.syncLoopVideo) box.syncLoopVideo();
      if (box.offsetParent !== null) startLoopVideo(box);
    });
  }
  startVisibleVideos();
  var resizeTimer = null;
  var onResize = function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(startVisibleVideos, 300);
  };
  window.addEventListener("resize", onResize);
  // 横竖两套构图的切换点（和 CSS 一样是 700px）：跨过时一定会通知
  var layoutQuery = window.matchMedia ? window.matchMedia("(max-width: 700px)") : null;
  if (layoutQuery && layoutQuery.addEventListener) layoutQuery.addEventListener("change", onResize);

  stages.forEach(function (stage) {
    // ---------- 图片加载状态 ----------
    var img = stage.querySelector("[data-scene-img]");
    if (img) {
      var done = function () {
        stage.classList.remove("is-loading");
      };
      var fail = function () {
        stage.classList.remove("is-loading");
        stage.classList.add("img-failed");
      };
      if (img.complete) {
        img.naturalWidth ? done() : fail();
      } else {
        img.addEventListener("load", done);
        img.addEventListener("error", fail);
      }
    }
    // ---------- 入口：悬停、聚焦、点击 ----------
    stage.querySelectorAll(".hotspot, .region-label").forEach(function (link) {
      var regionId = link.dataset.region;
      link.addEventListener("pointerenter", function () {
        setRegionClass(stage, regionId, "is-hover", true);
      });
      link.addEventListener("pointerleave", function () {
        setRegionClass(stage, regionId, "is-hover", false);
      });
      // 键盘聚焦：柔光亮起，名称标签出现焦点框（热区本身是透明的大块区域，不画方框）
      link.addEventListener("focus", function () {
        setRegionClass(stage, regionId, "is-hover", true);
        if (link.matches(":focus-visible")) setRegionClass(stage, regionId, "is-focus", true);
      });
      link.addEventListener("blur", function () {
        setRegionClass(stage, regionId, "is-hover", false);
        setRegionClass(stage, regionId, "is-focus", false);
      });

      link.addEventListener("click", function (event) {
        // 按住 Ctrl / Cmd 等想在新标签页打开时，不拦截
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        if (reduceMotion) {
          activate(link);
          return;
        }
        setRegionClass(stage, regionId, "is-pressed", true);
        setTimeout(function () {
          activate(link);
          // 打开面板的情况下，回到正常状态
          setRegionClass(stage, regionId, "is-pressed", false);
        }, 220);
      });
    });

    // ---------- 动物：点一下随机做一个动作，飘出一颗爱心 ----------
    var reactions = ["react-wave", "react-tilt", "react-hop"];
    var moodPanel = document.getElementById("mood-panel");
    stage.querySelectorAll("[data-animal]").forEach(function (animal) {
      animal.addEventListener("click", function () {
        sound.play("pet_touch"); // 主动摸一摸小动物
        // 点自己的动物：打开心情选择（只能选自己的心情）
        if (animal.hasAttribute("data-mood-picker") && moodPanel && moodPanel.showModal) {
          moodPanel.showModal();
          return;
        }
        if (reduceMotion) return;
        reactions.forEach(function (r) {
          animal.classList.remove(r);
        });
        void animal.offsetWidth; // 让同一个动画可以连续重新播放
        animal.classList.add(reactions[Math.floor(Math.random() * reactions.length)]);

        var heart = document.createElement("span");
        heart.className = "float-heart";
        heart.style.left = parseFloat(animal.style.left) + parseFloat(animal.style.width) / 2 + "%";
        heart.style.top = animal.style.top;
        stage.appendChild(heart);
        setTimeout(function () {
          heart.remove();
        }, 1200);
      });
      animal.addEventListener("animationend", function (event) {
        if (event.animationName.indexOf("react-") === 0) {
          animal.classList.remove("react-wave", "react-tilt", "react-hop");
        }
      });
    });
  });

  // 从功能页按浏览器"返回"回到首页时，页面可能是缓存的，清掉按压状态
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".is-pressed").forEach(function (el) {
      el.classList.remove("is-pressed");
    });
  });

  // 面板：点击面板外的半透明背景也可以关闭（Esc 关闭由浏览器自带）
  document.querySelectorAll("dialog.panel").forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
  });

  // ---------- 两只动物的名牌（含下方的心情标签）不能重叠 ----------
  // 名牌位置按场景百分比摆放，屏幕窄或名字 / 心情文字长时可能挤在一起。
  // 这里量一下两张名牌的实际大小，重叠时各自往外推一半（不超出场景边缘）。
  function chipBox(chip) {
    // 名牌 + 下方心情标签合在一起的范围
    var box = chip.getBoundingClientRect();
    var left = box.left, right = box.right, bottom = box.bottom;
    var pill = chip.querySelector(".chip-mood");
    if (pill) {
      var p = pill.getBoundingClientRect();
      left = Math.min(left, p.left);
      right = Math.max(right, p.right);
      bottom = Math.max(bottom, p.bottom);
    }
    return { left: left, right: right, top: box.top, bottom: bottom };
  }

  function separateChips(stage) {
    var chips = Array.prototype.slice.call(stage.querySelectorAll("[data-name-chip]"));
    if (chips.length < 2) return;
    chips.forEach(function (chip) {
      chip.style.setProperty("--nudge-x", "0px");
    });
    var area = stage.getBoundingClientRect();
    if (!area.width) return; // 这个版式现在没显示（例如手机版式）
    var boxes = chips.map(chipBox);
    // 按横向位置排好：a 在左，b 在右
    var order = boxes[0].left + boxes[0].right <= boxes[1].left + boxes[1].right ? [0, 1] : [1, 0];
    var a = boxes[order[0]], b = boxes[order[1]];
    var gap = 8;
    var overlapX = a.right + gap - b.left;
    var overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (overlapX <= 0 || overlapY <= 0) return;

    var moveA = overlapX / 2, moveB = overlapX / 2;
    // 不要推出场景：一边到边了，就让另一边多走一些
    var roomA = a.left - area.left - 4, roomB = area.right - 4 - b.right;
    if (moveA > roomA) { moveB += moveA - Math.max(roomA, 0); moveA = Math.max(roomA, 0); }
    if (moveB > roomB) { moveA += moveB - Math.max(roomB, 0); moveB = Math.max(roomB, 0); }
    chips[order[0]].style.setProperty("--nudge-x", -moveA + "px");
    chips[order[1]].style.setProperty("--nudge-x", moveB + "px");
  }

  var separateAll = function () {
    stages.forEach(separateChips);
  };
  separateAll();
  window.addEventListener("load", separateAll);
  window.addEventListener("resize", separateAll);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(separateAll);

  // ---------- 新用户第一次进入小岛：温和地引导去初见森林 ----------
  var intro = document.getElementById("forest-intro");
  if (intro && intro.showModal && intro.hasAttribute("data-open-on-load")) {
    intro.showModal();
  }
})();
