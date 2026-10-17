// 初见森林页面：每 4 秒问一次服务器，另一半测完（或重测）时自动刷新，
// 这样两只动物和"你们的组合"会立刻出现。页面在后台标签页时暂停。
(function () {
  var root = document.querySelector("[data-forest][data-state-url]");
  if (!root) return;
  var version = root.dataset.version;

  var check = function () {
    if (document.hidden) return;
    fetch(root.dataset.stateUrl, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        if (resp.status === 401) {
          window.location.reload();
          return null;
        }
        return resp.ok ? resp.json() : null;
      })
      .then(function (data) {
        if (data && data.version !== version) {
          if (window.UslandSound) window.UslandSound.expectLive();
          window.location.reload();
        }
      })
      .catch(function () {
        // 网络暂时不通，下次再试
      });
  };

  setInterval(check, 4000);
  document.addEventListener("visibilitychange", check);
})();
