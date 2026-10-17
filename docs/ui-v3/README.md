# Usland UI asset pack

本包已更新为第三版。请先阅读 `交付必读-v3.md`，以其中说明和当前定位配置为准。已包含16种结果动物；海岛专用姿态、雕像与和好姿态由队友继续制作。

## 当前验收限制（请先阅读）

- 背景为生成的位图，输出尺寸由原生生成图缩放得到，不是同尺寸原生3D渲染。
- hotspots 和 interactive 已改成无背景柔光反馈，鼠标/键盘热区由HTML负责。开门、开盖等局部造型动画仍需队友提供独立物件切图。
- scene_anchors.json 已用结果动物完成桌面与手机合成验收。队友交付新的海岛姿态和雕像后，仍需按其真实脚底枢轴做一次微调。
- 回忆场景已去除角落生成标记；用户照片进入倾斜相框时仍需HTML/CSS透视遮罩。
- 动画 WebP 是亮度与装饰光点原型，不等同于清单要求的真实海浪、烟雾、灯光MP4循环。两项MP4未交付。
- 本包提供视觉变量与交接规范，未创建或验证实际Figma文件。
- 不应将文件数量视为验收通过数量，具体状态见 asset_manifest.json。
- 资源自动检查结果见 `qa_report.json`；第二版当前为 PASS。

## 本轮改进

- `intp.png` 已补齐身体与双脚之间的缺失区域；`entj.png` 已补齐被裁掉的脚掌。
- 16张结果角色统一为1024×1024画布，脚底基准统一到 y=963。
- 重复人格角色的 `default_a/default_b` 已移入 `assets/animals/deprecated-defaults/`，运行时测试前使用中性占位。
- 电脑和手机的五个功能背景都按主岛粘土材质重新统一，回忆页角落生成标记已去除。
- 原来带天空和草地的伪透明热区已替换为纯透明柔光反馈，体积显著下降；点击继续由HTML热区负责。
- `integration/demo.html` 可切换任意两种动物，检查桌面与手机的实际合成。
- `integration/character_asset_contract.json` 定义了队友后续雕像、海岛姿态和和好姿态的文件路径与枢轴要求。

## Delivered

- Desktop and mobile island masters with five landmarks, a shared empty picnic blanket for player placement, and two empty forest pedestals.
- Background-free focus/hover overlays for the cottage, pier, quest board, forest, and mailbox.
- Statue contact-shadow overlays and cottage highlight states.
- Five function-scene backgrounds in desktop and mobile sizes.
- Memory-room interactive layers for frames, album, and postcards.
- Usland logo, favicon, neutral avatar/photo placeholders, player placeholders, and 18 interface icons.
- `integration/scene_anchors.json` with separate desktop/mobile coordinates for player animals, statues, and hotspots.
- `integration/tokens.css` with the visual tokens used by the asset family.
- `asset_manifest.json` with dimensions, color mode, frame counts, and delivery status.
- Sixteen normalized result animals and animated WebP island-loop prototypes.

## Animal and statue replacement

Load the island background first. Place each player animal using the corresponding `players.left` or `players.right` anchor in `integration/scene_anchors.json`. Before a result exists, display `player_slot_left.png` or `player_slot_right.png` (default clay figure: open eyes on the left, big smile on the right) instead.

For the island forest, render the contact shadow below the statue, then place each teammate-provided statue at its matching `statues.left` or `statues.right` foot anchor. The stone pedestal is already in the base. These anchors apply to the island, not the separate forest quiz background. A single completed result can replace one side while the other remains empty.

Result animals use a normalized transparent 1024×1024 canvas and y=963 foot baseline. Teammate-provided island poses, statues and reconcile poses may use 1536×1536, following `integration/character_asset_contract.json`. Do not bake names or labels into images.

## Figma setup

Import `tokens.css` values as a `Usland / Core` variable collection. Create two scene frames at 2560×1440 and 1440×2560. Place each full-canvas layer at x=0, y=0 with no scaling. Add component properties for `state=default|hover|focus|selected` and use the supplied hotspot/glow layers as state swaps. Keep all Chinese and English labels as Figma text and later HTML, never rasterized into a scene.

## Motion note

The current environment could not encode H.264 MP4. The two requested MP4 rows remain marked `deferred` in `asset_manifest.json`; matching five-second animated WebP fallbacks are included and can be used immediately. If MP4 is required, encode the fallback or source background at 24 fps, 4–6 seconds, silent, fixed camera, and preserve the first/last-frame loop.
