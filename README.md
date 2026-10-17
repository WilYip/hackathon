# Usland

两个人的小岛：温柔传话、约会选选选、初见森林、回忆小屋。完整需求见 `USLAND_SPEC.md`，开发进度见 `PROGRESS.md`。

> 完整的目录说明会在 M8 补充。

## 本地运行

```powershell
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python app.py
```

打开 http://localhost:8080 。

## 部署到 Zenith

项目根目录已经准备好 `Dockerfile`、`.dockerignore` 和 `zenith-compose.yml`（`zenith check` 已通过）。
Zenith 会用 `Dockerfile` 构建镜像，用 gunicorn 在 8080 端口运行；数据库、上传的照片和自动生成的
`SECRET_KEY` 都放在持久卷 `usland_data`（容器里的 `/app/data`）。不需要配置任何环境变量。

需要 Node.js 20.10 以上。在项目根目录：

```powershell
npm install -g @zenith-hosting/cli
zenith auth login          # 会打开浏览器登录并授权
zenith check --upload-size # 本地检查，不上传
zenith up                  # 上传当前文件夹，构建一个约 20 分钟的临时网址用来测试
zenith logs --source runtime
zenith down                # 测完关掉
```

正式上架（提交审核）用 `zenith publish`：它从 **GitHub 上的公开仓库**里指定的提交构建，需要你对仓库有
所有者或管理员权限、在 https://app.zenith.hosting/publish 连接 GitHub、同意开发者协议，并准备至少一张截图。
上架前请给仓库加一个 `LICENSE` 文件，并把 `zenith-compose.yml` 里的 `license` 改成同一个许可证。

## 声音

- 全站声音由 `static/js/sound.js` 统一管理（背景音乐、环境声、音效），**默认关闭**；在首页左上角或小信箱里打开。
- 素材清单：`content/audio_manifest.json`（路径、建议音量、是否循环、来源、授权、加工记录）；事件对照：`docs/event_map.md`。
- 背景音乐体积优化：安装 ffmpeg 后运行 `python scripts/compress_bgm.py`（先用 `--dry-run` 预览），原文件会备份到 `data/audio_originals/bgm/`。

### 音频来源与授权

音频素材来自 OpenGameArt 与 Kenney 已发布的作品，经过转码、音量/均衡调整、首尾淡化和剪辑。完整署名见 [`static/audio/credits.html`](static/audio/credits.html)（网站内：小信箱 →「音乐致谢」）和 `docs/credits.md`，许可证与来源证明在 `docs/licenses/`。

**需要署名（CC BY 3.0，https://creativecommons.org/licenses/by/3.0/）**——作者 MouthlessGames，专辑 *Snowy Cozyness (Calm Piano/Guitar)*，来源 https://opengameart.org/content/snowy-cozyness-calm-pianoguitar ；改动：重命名、转为 MP3、音量/均衡调整、首尾淡化：

| 原曲 | 在 Usland 中 |
|---|---|
| A Warm Fireplace | `static/audio/bgm/bgm_welcome.mp3`（欢迎与登录） |
| It's Getting Freezing Cold | `static/audio/bgm/bgm_quest.mp3`（约会选选选） |
| I Never Came Home Again | `static/audio/bgm/bgm_memories.mp3`（回忆小屋） |

**CC0 1.0（公共领域，无需署名，仍列出以示感谢）**：Sunset Plains — Yoiyami；Revelation — Indieteur；Forest Ambience — TinyWorlds；Beach Ocean Waves — jasinski（qubodup 上传）；Park ambiences — Thimras；Fireplace Sound loop — PagDev；100 CC0 SFX — rubberduck；RPG Audio、Interface Sounds、Music Jingles — Kenney。

如果用 `scripts/compress_bgm.py` 重新压缩了背景音乐，属于"转码"改动，署名要求不变。
