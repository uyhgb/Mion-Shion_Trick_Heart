---
name: pv-line-boil
description: Use when replaced characters in a hand-drawn-style PV look static or "too clean" against a boiling (redrawn-every-few-frames) background — measure the source's per-shot redraw schedule and apply deterministic A/B texture variants (flat fill, stroke-width jitter, smooth low-amplitude displacement) to the new character layers. No image generation.
---

# 线条抖动与质感还原

手绘 PV 的静止镜头往往是两张（或几张）略有不同的整幅重描稿，按固定节奏切换。换上去的人物如果是一张静图，就会和抖动的背景割裂。本 Skill 用确定性后处理补上这一层，不调用生图，身份不会走样。

工具：仓库里的 `tools/pv_boil.py`（`measure` / `variants` / `pick`），以及自测 `tools/test_pv_boil.py`。

## 步骤

1. **测时刻表（每镜单独测）**
   - 对每个人物镜头，在人物区域内逐帧差分，找出「整幅重描」的帧；把真正的姿态切换帧（来自 pose-events）和小元素的动画（星光、文字、睡眠符号）排除掉。
   - 把各段 hold 聚类成重复出现的相位（A、B、……）；用光流测出两次重描之间的线条位移（中位数、p90）。
   - 不能假设统一的「6 帧」；首次切换不一定在镜头首帧；有的镜头里不同人物各有各的节奏。
   - 产物：`boil-schedule.json`（每镜的 holds、boilFrames、位移）。无人物镜头登记为 `no-character`。

2. **做变体（在输出像素空间里）**
   - 人物缩放、摆位、跟踪之后，裁切和恢复源片前景之前，对图层做处理。
   - 顺序：保护区（瞳孔、接触道具和托着它的手、源片像素部分）→ 平涂（共用调色板，限制单像素颜色偏移，线条不动）→ 线条（只认近黑细线，排除大块黑色填充；线宽 ±0.55 px 低频变化，加少量断笔）→ 平滑位移场（大 100 px、小 18 px，按实测中位数归一化，A/B 对称取 ±F/2，预乘 alpha 重采样）→ 脸部强度减半（羽化）。
   - 种子由「镜头 | 资产 | 相位 | 用途」哈希得到；同一相位的帧完全一致，只在重描帧切换，**绝不每帧随机**。

3. **样镜先行**
   - 选三个镜头：一个开场替换镜、一个站立双人镜、一个最长的静止双人镜（最能看出割裂）。
   - 每镜导出「源片 / 现版 / 质感版」三联同步视频，以及抖动前后的放大图。
   - 参数写进 `texture-params.json`。作者批准后加哈希、只读。

4. **推广（可并行）**
   - 按时间线分组，每组只写本组目录；个别镜头的特殊处理写进本组的 `param-overrides.json` 并说明原因。
   - 别漏掉的地方：
     - 只露手的镜头里新画的前臂和袖口，要跟着同一时刻表抖；
     - 整层替换的镜头也要抖；
     - 快速换姿态的段落，只在同一张原画保持的区间内抖；
     - 被完全遮挡的帧不用处理。

5. **合并**
   - 拼出完整时刻表；用各组的**无损帧缓存**加上样镜的无损重渲染，拼成全片。样镜不要从已编码的 MP4 解码再编码。
   - 检查分组交界和跨切点处有没有相位跳闪；先无声编码，再用原音轨 stream copy。

## 验收

- 原速播放时，人物和背景是否一起「呼吸」。
- 五官有没有变形。
- 有没有硬色阶或脏色块，重点看腮红、徽章、小面积的强调色。
- 同一相位的帧逐帧哈希是否一致。
- 支持区（人物）之外的 RGB 变化是否为 0。

## 限制

后处理不会改变线条的拓扑：如果原画线条本身太多太碎，只能针对少数镜头重画。
