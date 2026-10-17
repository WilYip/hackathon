# Usland 事件映射补充

| 场景/动作 | 声音 |
|---|---|
| 欢迎/创建/加入/登录 | bgm_welcome；成功ui_success |
| 复制邀请码、另一位成员首次加入 | ui_success，每事件一次 |
| 首页 | bgm_island，可配amb_ocean |
| 进入回忆小屋 | cottage_open；bgm_memories，可配amb_cottage |
| 进入传话码头 | dock_enter；bgm_whisper，可配amb_dock |
| 进入告示牌 | board_open；bgm_quest |
| 进入森林 | forest_enter；bgm_forest，可配amb_forest |
| 进入小信箱设置 | mailbox_open；沿用首页音乐 |
| 选答案、约会条件、开关 | ui_select |
| 保存昵称/岛名、API测试和删除成功 | ui_success |
| AI草稿返回 | draft_ready；不表示发送 |
| 确认发送成功 | message_send；直接发送共用 |
| 对方新消息/约会提议/新任务轮次 | message_receive，按事件去重 |
| 对方收到和好邀请 | reconcile_invite |
| 双方和好成功 | reconcile_complete，不另播memory_save |
| 推荐任务首次显示 | quest_reveal |
| 双方同意同一任务 | quest_agreed |
| 任务与回忆保存完成 | quest_complete，不另播memory_save |
| 个人动物结果 | animal_reveal |
| 双人组合首次显示 | pair_reveal，不另播memory_save |
| 手动新增回忆成功 | memory_save |
| 查看回忆/放大照片 | memory_open |
| 主动触摸动物/动物实际移动 | pet_touch / pet_steps |
| 关闭面板/取消草稿/关闭照片 | ui_close |
| 登录失败、网络失败、次数用尽 | 文字反馈；ui_error默认可关闭 |
| 安全提示、打字、AI等待、滚动、悬停、轮询 | 静音 |
| 等待对方加入或选择 | 当前背景声，无催促 |
| 退出登录 | 音乐淡出，不加专属声 |

设定一个全局声音管理器，避免多个功能页各自创建无法停止的播放器。
