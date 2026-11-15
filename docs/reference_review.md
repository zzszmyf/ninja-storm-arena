# 美术与开源参考评估

这份清单记录可以借鉴的资源和项目，并把授权边界写清楚。当前项目的 SORA、KAZE、黄昏村场景和音频是项目内已有内容；外部资源先作为参考，只有明确满足授权和画风要求时才进入仓库。

## 推荐使用

| 来源 | 可借鉴内容 | 授权/注意事项 | 本项目决定 |
| --- | --- | --- | --- |
| [Kenney UI Pack](https://kenney.nl/assets/ui-pack) | 菜单边框、按钮、状态面板的布局思路 | Kenney 资产页使用 CC0；支持页允许商业使用且不要求署名 | 参考组件层级和间距，必要时只引入中性 UI 图标 |
| [Kenney Particle Pack](https://kenney.nl/assets/particle-pack) | 命中火花、烟尘、飞散粒子 | CC0；80 个 2D 粒子文件 | 参考粒子形状和颜色分层，优先继续使用现有 `scripts/fx.gd` 生成特效 |
| [Kenney Game Icons](https://kenney.nl/assets/game-icons) | 气槽、暂停、设置等小图标 | CC0；105 个图标 | 可用于后续设置页和操作说明，不替换角色与场景美术 |
| [GoHitHurt](https://github.com/wokidoo/GoHitHurt/) | Hitbox/Hurtbox 节点、命中信号、逐帧启停 | MIT | 作为判定系统重构参考；当前 Rect2 数据判定稳定，暂不直接复制代码 |
| [Mugen Remake](https://github.com/zeak6464/Mugen-Remake) | 数据驱动招式、角色选择、对战流程、编辑器方向 | 先作为架构参考，复制代码前必须复核仓库许可证 | 当前 JSON 技能管线继续沿着“数据和表现分离”扩展 |

## 只作研究，不直接混入

| 来源 | 原因 |
| --- | --- |
| [Ninja Adventure](https://tmhsdigital.github.io/Free-Game-Dev-Assets/entry/ninja-adventure/) | CC0 且适合做原型，但它是 16x16 俯视/3/4 像素风，和本项目侧视手绘角色不一致 |
| [AutoSprite Ninja](https://www.autosprite.io/free-sprite-sheets/ninja) | CC0、侧视动画较接近，但素材比例和笔触仍与 SORA/KAZE 不统一 |
| [Hackfighter](https://github.com/quarker1337/hackfighter) | Godot 4 2D 格斗项目很适合学习资源组织；仓库明确把代码许可和素材许可分开，不能把 `assets/` 当作统一 MIT 资产复制 |
| [Field Trip Fighters](https://github.com/patkilleen/field_trip_fighters) | Apache-2.0 的旧 Godot 3 示例，可看状态机组织，但版本和表现层都较旧 |

## 落地规则

1. 角色、场景、关键招式特效保持同一套手绘动漫视觉语言。
2. 外部素材进入仓库前，必须在 `docs/asset_sources.md` 记录原始 URL、下载日期、许可证和使用位置。
3. 许可证没有明确写出的 GitHub 素材不复制；只阅读代码结构和设计思路。
4. UI 和粒子优先做成可替换资源，玩法代码不依赖某个外部素材包。

## 下一步开发顺序

1. 完成战斗内 UI 的图标化：气槽、暂停、技能冷却和操作说明统一使用可替换图标槽位。
2. 将命中框调试显示做成开发开关，继续保持数据驱动。
3. 在现有技能 JSON 上增加可选的粒子主题字段，让不同角色的命中效果能换色而不改判定逻辑。
4. 需要更多角色时，先制作统一比例的原创角色包，再考虑补充外部 CC0 原型素材。
