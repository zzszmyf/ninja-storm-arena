# 会话状态 / Session State

## 当前目标 / Current goal

- 本轮继续开发：补上了可随时使用的暂停层。`P` 暂停/继续，暂停时战斗物理、倒计时、镜头抖动和 BGM/气 aura 都保持住；暂停中按 `R` 仍可直接重开。
- 本轮继续开发：加入受击中脱身的替身术，P1 `Q`、P2 `右 Shift`，消耗 28 气、冷却 180 帧、12 帧无敌，并在原位置与脱身位置生成烟雾特效。
- 本轮继续开发：新增策划可配置的 `ultimate` 超必杀槽。P1 `U`、P2 `K`，消耗 60 气、冷却 300 帧，KAZE/SORA 都已配置“奥义·裂空斩”，CPU 也会按距离和权重使用。

- 用户最新指令：**「这游戏为啥运行卡顿」** → 定位到「60 Hz 逻辑 vs 120 Hz 渲染、中间没有插值」，
  用户回「按照你说的做吧」后按方案 A 修好（渲染锁 60），并顺手修掉它暴露出来的随机数污染。见本轮。
- 上一条指令（已完成）：**「自动朝向 就行，先做个技能管线出来，这个然后技能管线是策划人员可以配置的，
  生成配置，游戏加载配置生效」**。
- 前一句「跟交互有关，王者荣耀、英雄联盟的交互就很好，就几个按键、qwer 类似的」= 少按键、槽位化：
  已经落成 `basic / air / skill_1 / skill_2 / jutsu` 五个槽，一人四个攻击键 + 一个忍术键。
- 音效侧的旧目标（暂停中）：把整套音效从「一听就是合成器」改到能过耳朵（EARS 听感评审）。

## 本轮做完的事 / Done this round（2026-09-21，性能）

- **定位「卡顿」＝帧不对齐，不是跑不动**：角色位置只在物理帧（60 Hz）更新，渲染跟着 120 Hz
  ProMotion 屏跑，中间没有插值。实测（`tests/perf.gd`）：120 FPS 下**一半的渲染帧物理步数 = 0**，
  移动中 **59% 的渲染帧和前一帧坐标完全相同**，而且重复帧数在 2 和 3 之间乱跳。
- **排除「太 heavy」**：新增 `tests/_perf_hot.gd`，关掉垂直同步量真实开销——全开 4.55 ms/帧（220 FPS），
  分别藏掉角色 / HUD / 背景 / 静音，帧时间差值全在 0.3 ms 以内。音效共 4 MB 且全部走缓存，也不是加载问题。
- **修复（方案 A，用户选定）**：`project.godot` 加 `run/max_fps=60`，渲染与物理同频。
  验证：每渲染帧 1 步 = 420/420，两次物理步间隔「隔 1 帧」= 100%。
  ⚠️ 坑：`project.godot` **只认 `;` 注释，`#` 会让那一行设置静默失效**（第一次就栽在这里：值读出来还是 0）。
- **被修复暴露出来的真 bug：装饰性代码在消费全局随机数**。`main.gd:_update_shake` 每渲染帧抽 2 个
  `randf_range`，`bg.gd` 落叶回绕抽 1 个，而 CPU 选招用的是同一个全局流 → **帧率一变，CPU 打出来的拳就变**。
  已给镜头抖动 `_shake_rng`、落叶 `_rng` 各自的 `RandomNumberGenerator`，并在 trauma = 0 时直接跳过。
- **两个「固定种子」其实是假的**：`skills_check.gd` / `audio_check.gd` 都在 `_initialize()` 里 `seed()`，
  但 `Main._ready()` 的 `randomize()` 会把它冲掉 → 覆盖度检查靠运气（实测 audio_check 20 次里失败 2 次，
  skills_check 也偶发失败）。已在采样开始前重新 `seed()`，并把「AI 会不会跳」改成像气功弹那样
  用真实调用驱动（`_drive_hop` 给站着的角色写 jump buffer）。现在 12 个种子 12 次全过。
- `README.md` 新增「性能」章节（为什么锁 60、怎么复测、装饰性代码不许用全局随机数）。

## 上一轮做完的事 / Previous round（2026-09-21，技能管线）

- **技能管线打通**：`data/skills/<slug>.json`（策划手写）→ `tools/skills_build.py`（校验+生成+打印帧数据表）
  → `data/characters.generated.json`（游戏只读它）→ `scripts/skill_db.gd`（唯一读配置的地方，坏了才用内置兜底）。
- **CPU 也读同一张表**：新增 `ai.range / ai.min_range / ai.weight` 真正被运行时消费（`fighter.gd:_ai_pick_slot/_ai_cast`），
  以前这三个字段只被构建工具校验、运行时根本没读——属于「配置骗人」。
- **补齐两个技能槽**：KAZE/SORA 各加 `dash_strike`（skill_1，突进）与 `rising_kick`（skill_2，挑空耗气），
  两个人的数值刻意不同（KAZE 快、SORA 重）。之前 skill_1/skill_2 是空数组，按键无反应。
- **策划手册**：`docs/skills.md`（字段表、帧优势公式与判定表、加招/加角色的步骤、工具会挡住的坑）。
- **回归测试**：`tests/skills_check.gd`（104 项，配置→场上的角色全部走一遍，含「整局 AI 真的用到配置技能槽」）。
- **修好被重构漏掉的音频测试**：`tests/audio_check.gd:_drive_technique` 还在调已删除的 `_start_proj()`，
  改成走配置（`SkillDb.first_of(slug, "jutsu")` + `_start_move`）。
- README 更新（按键、代码结构、技能配置章节、自动测试清单）。

## 验证记录 / Verified

- `python3 tools/skills_build.py` → source_hash `218caab7a98dc7f6`，2 个角色，无错误无警告。
- `python3 tools/skills_build.py --check` → 配置 OK。
- `tests/skills_check.gd` → SKILLS OK: 104 checks passed（seed 1 / 3 / 7 / 11 都过）。
- `tests/smoke.gd` → SMOKE OK（AI 用新技能后仍能打完一局，1422–1950 帧）。
- `tests/audio_check.gd` → AUDIO OK: 97 checks passed。
- **端到端证明「配置生效」**：把 KAZE 的 `hp` 100→90、重新生成，测试仍全绿（场上角色的血量来自配置而非硬编码）；再改回 100。
- **反证（证明测试不是摆设）**：①删掉生成文件 → 10 项失败；②改 json 不重新生成 → `--check` 失败；
  ③把两个技能槽的 `ai.weight` 改成 0 → 「CPU 真的用了配置的技能槽」失败。
- 画面：`tests/shots.gd` 出图，用 gemini-2.5-pro 看图确认 HUD 完整、两个角色与擂台正常、无渲染错误。

本轮（性能）新增：

- `tests/perf.gd base`（出厂配置、开窗口）→ 平均 16.67 ms / 60.0 FPS，**每渲染帧物理步数 1 步 = 420/420**，
  修饰前同一命令是 8.33 ms / 120 FPS 且 0 步 = 210 / 1 步 = 210。
- `tests/_perf_hot.gd default` → 60 FPS，0 步的帧 0%，两次物理步间隔「隔 1 帧」= 600/600；
  修饰前是 120 FPS、0 步 50%、间隔在「隔 2 帧」和「隔 3 帧」之间乱跳。
- 真实开销（`_perf_hot raw` 关垂直同步）：4.55 ms/帧 = 220 FPS；`nofighters` 4.49 / `nohud` 4.43 /
  `nobg` 4.68 / `nosfx` 4.57——差异全在噪声内，证明不是绘制或音频的锅。
- 回归：`SMOKE OK`（668–672 帧）· `SKILLS OK 104 checks`（seed 1/3/7/11/42/99/1234 全过）·
  `AUDIO OK 97 checks`（seed 1–12 全过；修复前 20 次随机跑里会失败 2 次）· `skills_build.py --check` 配置 OK。
- 画面：`tests/shots.gd` 出 4 张图（intro / fight_start / fight_a / ko），像素统计 12–27 万独立颜色、
  无整屏单色，确认没有渲染坏掉（本会话看不了图，改用像素统计代替肉眼）。

## 已确认决策与原因 / Confirmed decisions & reasons

- **判定框是数据，动画只是表现**：招式的启动/活跃/收招、判定框、硬直、击退、顿帧、取消窗口全部来自配置；
  `fighter.gd` 只知道「怎么跑一招」，不知道「有哪些招」。加招＝改配置，不改代码。
- **帧优势由工具算，不靠人脑**：`skills_build.py` 打印 `hitstun − 剩余帧[(active−1)+recovery]` 的表，
  并写进生成的配置（`frame_advantage`）；`skills_check.gd` 会重算一遍，防止表和配置不一致。
- **绝不让半成品配置进游戏**：pose/音效名/id/取消链/槽位引用任一写错，构建工具报错并且**不生成**文件。
- **朝向自动**：`_update_facing()` 每帧朝对手翻面，只在出招/被 KO 时锁定，不设转身键。
- **渲染锁 60，和物理同频**：60 Hz 逻辑 + 无插值 + 120 Hz 渲染 = 同一个状态被重复画 2~3 帧，
  看着就是卡。`project.godot` 的 `run/max_fps=60` 是刻意设置，别当遗留物删掉。真上 120 Hz 要升
  Godot 4.4+ 开 `physics_interpolation`，或自己写插值。
- **`project.godot` 只认 `;` 注释**：用 `#` 会让紧跟着的那行设置静默失效（值读出来是默认值，不报错）。
- **装饰性代码不许用全局随机数**：全局 `randf()` 流是玩法的（CPU 选招、音效变调），只能按物理帧抽。
  镜头抖动用 `main.gd:_shake_rng`，落叶回绕用 `bg.gd:_rng`。否则改帧率就会改 CPU 的行为。
- **测试里 `seed()` 要在 `Main._ready()` 之后再调一次**：`_ready()` 里的 `randomize()` 会把 `_initialize()` 里的种子冲掉，
  覆盖率类断言就会变成掷骰子（`skills_check.gd` / `audio_check.gd` 都已按这个修）。
- **靠运气的覆盖度断言要「驱动」而不是「祈祷」**：AI 会不会跳/放气功弹都是硬币，
  用游戏自己的调用把它逼出来（`audio_check.gd:_drive_technique` / `_drive_hop`），失败才真的代表音频坏了。
- **不要用 `open -a Godot --args --path …` 启动**：会被 macOS 文稿夹 TCC 授权卡死（进程在、窗口没有、CPU 0%）。
  走 `开始游戏.command` 或直接跑 `/Applications/Godot.app/Contents/MacOS/Godot --path .`。
- **从本会话后台起的 Godot 会在会话结束后被回收**，所以「我帮你开着游戏」不可靠；要玩请让用户双击 `.command`。
- **截图必须去掉 `--headless`**（dummy renderer 下 `root.get_texture()` 是 null）；无头测试则相反。
- **Godot 全局 class 缓存只在编辑器扫描时刷新**，所以新脚本一律 `preload`，不靠 `class_name` 全局名。
- 音频侧（暂停中，恢复时按这个来）：唯一源文件是 `tools/` 里的脚本，`assets/audio/**/*.wav` 是产物；
  改听感＝改脚本重渲染 + 跑 `tools/godot_reimport.py` 刷新导入缓存（缓存陈旧会让改动静默听不出来）。

## 涉及文件路径 / Involved file paths

- `data/skills/kaze.json`、`data/skills/sora.json`（策划改这里）
- `data/characters.generated.json`（产物，别手改）
- `tools/skills_build.py`（校验 / 生成 / 帧数据报告）
- `scripts/skill_db.gd`（加载配置；`SLOTS` / `AI_SLOTS` 在这里定义）
- `scripts/fighter.gd`（状态机 + `_ai_pick_slot` / `_ai_cast` / `_update_facing`）
- `project.godot`（`run/max_fps=60` 与 60 Hz 物理，两处必须一致）· `scripts/main.gd`（`_shake_rng`）· `scripts/bg.gd`（`_rng`）
- `docs/skills.md`（策划手册）· `README.md`（怎么跑、按键、测试清单）
- `tests/skills_check.gd`（技能管线测试）· `tests/smoke.gd` · `tests/audio_check.gd` · `tests/shots.gd`
- `tests/perf.gd`（帧时间/卡顿点）· `tests/_perf_hot.gd`（真实开销 + 帧节奏）
- 音频相关（暂停）：`tools/build_audio.py`、`tools/audio_report.py`、`tools/audio_ears.py`、`docs/audio_ears_sfx.md`

## 未完成事项 / Unfinished items

- [ ] 用户实际玩过之后的反馈：新技能（`L` 突进 / `I` 挑空）的手感，有没有卡住/报错。
- [ ] 技能槽目前**每槽只能放一招**（`basic` 是唯一有序连击串）；若要做「多招共享一键、按方向/时机分支」，
      需要给槽加列表语义。
- [ ] 没有投技、超必杀、防御反击这类进阶动作；替身术已加入（受击中 `Q` / `右 Shift`）。
- [ ] 没有选人界面：角色是 `main.gd` 里写死的 `sora` vs `kaze`（配置已支持多角色，缺的是 UI）。
- [ ] 配音/音效（暂停）：`hit_light` 仍不达标；foley 版还没重新做过 EARS 听感评审；试听文件待重做。
- [ ] **偶发尖刺未根除**：锁 60 后 420 帧里仍有约 3 帧超过 20 ms（个别到 40–60 ms），多出现在多特效同时存在的命中瞬间。
      量级是"偶尔掉一两帧"，跟本轮的帧对齐问题是两回事；要查就往「每次命中新建 Label + Tween」这类节点/补间churn 上查。
- [ ] **方案 B 未做（真 120 Hz）**：升 Godot 4.4+ 开 `physics/common/physics_interpolation`，或自己在 `_draw()` 里按物理累加器插值。
      会动引擎版本，需要重跑全部测试 + 两个探针。

## 下一步计划 / Next steps

1. 让用户双击 `开始游戏.command`，用 `L` / `I` 试新技能，收集手感反馈（数值就在 `data/skills/*.json`）。
2. 根据反馈调 `data/skills/*.json`：改完跑 `python3 tools/skills_build.py`，再看表、再试。
3. 想扩内容时优先「加招不加系统」：照 `dash_strike` 抄一份，改 pose / 帧数 / 取消窗口，填进槽位。
4. （音效恢复时）按旧计划处理 `hit_light` 的中频问题，重跑 EARS 评审与试听文件。
5. 双击 `开始游戏.command` 实际打一局：确认"卡顿"体感是否消失；若还有偶发一顿，按上面「偶发尖刺」那条查。
6. 想要真 120 Hz 顺滑再上方案 B（升 4.4+ 物理插值），上完必须重跑 `tests/perf.gd` 与 `tests/_perf_hot.gd` 确认节奏。

## 会话信息 / Session info

- 开始时间：2026-09-18；最近更新：2026-09-21（性能：定位卡顿 + 渲染锁 60 + 随机数污染 + 测试去抖）
- 工具/模型：Codex，Godot 4.3（`/Applications/Godot.app/Contents/MacOS/Godot`），Python（numpy 音频管线）
- 测试命令：`godot --headless --path . -s res://tests/skills_check.gd`（新增）· `-s res://tests/smoke.gd`
  · `--fixed-fps 60 -s res://tests/audio_check.gd` · `python3 tools/skills_build.py --check`
