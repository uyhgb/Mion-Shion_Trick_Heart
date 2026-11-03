# 分阶段提示词（交给执行 AI）

用法：
- 每段提示词开一个新对话贴进去。
- `{…}` 换成你的内容。
- 每段都会在停顿点停下；你审完、把意见写进 `analysis/project-brief.json` 的 `decisions` 以后，再贴下一段。
- 所有提示词都假定项目里已经有 `AGENTS.md`、`docs/00_进度看板.md` 和 `analysis/project-brief.json`，模板见 `templates/`。

---

## 0. 新对话接手（任何阶段，贴在提示词最前面）

```text
这是一个新对话，接手进行中的项目。动手前先读 docs/00_进度看板.md 和 AGENTS.md，再按 AGENTS.md 的必读顺序读完其余文件。用三五句话复述当前阶段、已定决策和环境注意事项，确认无误后执行下面的任务。
```

## 1. P0 + P1：拆镜，到 SP1 停

```text
使用 $trick-heart-pv 和 $ai-handdrawn-video。本项目把 MIMI「トリックハート」原PV的两位テト替换为 {角色A}（magician）和 {角色B}（casual），路线是「参考 PV 改编」。

P0：复核 analysis/input-manifest.json 的哈希，作者的人工标注字段原样保留；实测并写入 analysis/environment.md，包括 Python、FFmpeg 和真实可用的生图/改图能力（不写没验证过的模型版本）；导出 3 秒技术测试视频，并标明它不是美术样片。
P1：probe、shots、timeline（唯一的边界来源）、pose-events（逐帧记录入场/消失、转头、眨眼、张嘴、半睁眼、握住/放开、遮挡，不猜循环）、layers（每个物体只有一个来源）、text-cues（原PV文字保留源像素）、storyboard（每个镜头对回 docs/story-storyboard.md 的编号；对不上的列出来，不要硬凑）。可以参考 data/trick-heart-pv/ 的实测数据，但每个数都要在自己的源片上核对。
SP1 汇报：镜头总数与覆盖校验；牌面的精确帧区间；源片里角色外观变化的镜头；需要新画的原画张数粗估（按镜头类别分开）；实际看过的帧范围。更新看板后停下。
```

## 2. P2：角色母版，到 SP2 停

```text
使用 $trick-heart-pv，读取 $ai-handdrawn-video 的 references/character-and-motion.md 和 docs/character-card.md。SP1 结论：{你的意见}。

产物：
1. 七维画风规范，重点写清楚从厚涂到 3774. 扁平简笔怎么转，以及简化后必须保留的身份标志。
2. character-master.json：每个细节注明依据文件，色值只从立绘取。
3. expression-map.json：源片每个表情事件对应哪张参考立绘。
4. 母版：先出 {服装A} 的候选 {A/B…} 和 {服装B} 的正面全身；其他视角只画分镜实际用到的。
5. 对照图：双人同基线并排；遮发脸部对比；服装候选放在原PV背景上的效果；一帧双人镜头的合成试画。
6. 一张总览图 reviews/sp2/sp2-sheet.png。

规则：每张母版最多 6 次，落选也登记。服装结构逐项对照源帧（外套长度、手套袖口、腿部的左右差异、鞋）。不水平翻转。
SP2 汇报：验收清单逐条附证据图；列出你觉得最不像的至少 3 处；本轮生图次数。更新看板后停下。
```

## 3. 母版修订（可重复使用）

```text
SP2 作者意见：{逐条写}。只改被点名的问题，每张最多 {N} 次；生图端到端，不拼贴部件；验收「接近即可」。改不动就停下，报告哪一张、哪里不对。交一张修订前后的对照总览，更新冻结清单草稿（frozen=false），然后停下，等作者批准冻结。
```

## 4. 冻结 + P3-A 动态样片，到 SP3 停

```text
作者已批准母版：{清单}。先写正式冻结清单 assets/characters/frozen-masters.json（文件、SHA-256、适用范围、批准记录），旧版标为 superseded。
然后做 P3-A 四段样片：开场 s001–s005、杂耍 s057 中手形变化最密的约 2 秒、醒来 s069–s070、结尾 s075。每段输出源片和样片同步并排的视频（带原音轨片段）和关键事件帧拼图，列出新画了什么、复用了什么、哪些动作还没做到。每张原画最多 3 次，「接近即可」。停在 SP3。
```

## 5. P3-B 批量生产（主线）

```text
SP3 结论：方法通过；{需要修的接触问题}。全片规则：接触道具和手同图（道具独立运动时才用源道具层，同一帧每个道具只有一个来源）；只露手的镜头沿用源片的手，新画的前臂和袖口带线稿。
按七类镜头分批：01 静态跟踪 → 02 头像框 → 03 手部接触 → 04 背影风动 → 05 杂耍 → 06 帘幕沙发醒来 → 07 结尾。每批开工前列出原画清单和张数；做完回归同类全部镜头，导出并排预览，冻结本批资产，更新看板。批与批之间不用等我。上下文太长时，在批末停下让我开新对话。{如果有并行批次：本对话只做第 X 批，做完就停。}
```

## 6. P3-B 并行批次（每批一个对话）

```text
使用 $trick-heart-pv。本对话与其他对话并行，只制作 P3-B 的 {批次}，镜头见 reviews/p3b/batch-shot-map.json。
并行规则：只写 reviews/p3b/{批次}/、assets/shots/p3b/{批次}/、scripts/p3b_{批次}_*.py；共用文件（看板、generation-log、art-estimate、production-state、pose-events、project-brief、公用脚本）只读。在本批目录写 generation-log.jsonl、art-estimate-delta.json、pose-events-corrections.csv、handoff.md；开工时写 LOCK.json（in-progress），完成后改为 done。
本批要点：{按批次写，例如杂耍要复用已冻结的姿态、沙发镜头的兔子要和手同图、结尾的换装和扎发}。
完成后写 handoff.md，LOCK 改为 done，然后停下，不组装全片。
```

## 7. 合并 + P4 全片，到 SP4 停

```text
P3-B 七批都已完成（其中部分是并行做的）。先核对各批 LOCK.json 都是 done、每个镜头只有一个来源；再把各批的记录按时间顺序并回共用文件；pose-events 的修改建议逐条对照源片核实后再写入。
然后组装全片：统一渲染 → 无声编码 → 用源 AAC stream copy 独立封装（不重编码、不用 -shortest）→ 全片预览和左源右新对比版 → 检查全部 78 个切点（重点看跨批相邻的接缝）→ 待改表。停在 SP4。
```

## 8. P4s 质感还原：三个样镜，到停顿点

```text
使用 $pv-line-boil，参考 tools/pv_boil.py。本轮不调用生图。
1. 逐镜从源片实测抖动时刻表（区分整幅重描帧和姿态切换帧，不能套统一 6 帧），写入 analysis/boil-schedule.json。
2. 在输出像素空间里为人物图层做 A/B 变体：平涂（限制单像素颜色偏移）、近黑细线的线宽变化和断笔、按实测幅度的平滑位移、脸部减半、瞳孔和接触道具保护；种子固定，只在重描帧切换。
3. 先做三个样镜：{开场替换镜}、{站立双人镜}、{最长的静止双人镜}。每镜导出源片 / 现版 / 质感版三联同步视频和抖动前后的放大图；参数写入 analysis/texture-params.json。
不改冻结原画，处理结果另存。汇报实测节奏、振幅、参数，以及还不像的地方，然后停下。
```

## 9. P4s 推广（三组并行 + 合并）

```text
作者已批准样镜，参数文件只读（哈希 {…}）。本对话负责 {G1/G2/G3}：{镜头范围}。
只写 reviews/p4s/{组}/、output/p4s-work/{组}/、scripts/p4s_{组}_*.py；本组的时刻表写成 boil-schedule.part.json，需要特殊处理的镜头写进 param-overrides.json 并说明原因。只露手镜头里新画的前臂和袖口、整层替换的镜头也要跟着抖；杂耍只在同一张原画保持的区间内抖。帧按全局帧号存成无损 PNG。导出本组三联对比，写 handoff.md，LOCK 改为 done，然后停下。
```

```text
三组都已完成。先合并时刻表（旧文件先备份）；三个样镜从无损流程重新渲染，不要从已编码的 MP4 解码；然后拼全片 → 无声编码 → 原 AAC stream copy → 质感全片和对比版。检查分组交界、跨切点有没有相位跳闪。停在 SP4s。
```

## 10. P5 交付，到 SP5 停

```text
作者定稿：{终稿文件}。只做这些小修：{列出}，其余一律不动，不调用生图。导出 output/final.mp4（只编码一次，原 AAC stream copy）和 output/compare-source-vs-final.mp4。对实际的最终文件做 probe、完整解码、帧数和帧率核对、音频包和 PTS 与源片逐包比对、78 个切点抽帧，并和定稿预览逐帧比对。写 reviews/final-report.md（如实写明没做的检查，例如没有连续目视和试听）和 output/DELIVERY.md（文件位置、署名文字）。停在 SP5，不发布。
```
