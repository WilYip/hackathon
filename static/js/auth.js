// 账号相关页面的小脚本：显示 PIN、复制邀请码、等待另一半加入

// ---------- 显示 / 隐藏 PIN ----------
document.querySelectorAll(".show-pin-toggle").forEach(function (toggle) {
  toggle.addEventListener("change", function () {
    var form = toggle.closest("form");
    form.querySelectorAll(".pin-input").forEach(function (input) {
      input.type = toggle.checked ? "text" : "password";
    });
  });
});

// ---------- 复制邀请码 ----------
// navigator.clipboard 只在 https 或 localhost 下可用；
// 手机通过局域网 IP 访问时用旧方法 execCommand("copy") 兜底
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise(function (resolve, reject) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(area);
    ok ? resolve() : reject();
  });
}

document.querySelectorAll("[data-copy-target]").forEach(function (button) {
  button.addEventListener("click", function () {
    var code = document.getElementById(button.dataset.copyTarget).textContent.trim();
    var status = document.querySelector(".copy-status");
    copyText(code).then(
      function () {
        if (status) status.textContent = button.dataset.copied;
        if (window.UslandSound) window.UslandSound.play("ui_success");
      },
      function () {
        if (status) status.textContent = button.dataset.failed;
        if (window.UslandSound) window.UslandSound.play("ui_error");
      }
    );
  });
});

// ---------- 等待另一半加入 ----------
// 每 4 秒问一次服务器"小岛上有几个人了"，到齐后刷新页面；
// 页面在后台标签页时暂停查询，节省资源
var waitBox = document.querySelector("[data-wait-partner]");
if (waitBox) {
  var statusUrl = waitBox.dataset.statusUrl;
  setInterval(function () {
    if (document.hidden) return;
    fetch(statusUrl, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.ok ? resp.json() : null;
      })
      .then(function (data) {
        if (data && data.member_count >= 2) {
          // 另一半第一次加入：到首页再响一声（只响一次）
          if (window.UslandSound) window.UslandSound.next("ui_success", "partner_joined");
          window.location.href = "/";
        }
      })
      .catch(function () {
        // 网络暂时不通时什么都不做，下次再试
      });
  }, 4000);
}
