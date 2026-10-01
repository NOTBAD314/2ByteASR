# 字幕的转场与阅读期运动参考

2026-09-25：按用户要求，从视频过渡/转场插件寻找运动语法。以下是公开文档和目录的阅读记录；未下载插件，未宣称播放其演示。实现是作者对字幕场景的独立转译。

- [LookAE AE插件目录（用户指定）](https://www.lookae.com/after-effects/aechajian/page/2/)：转向插件和视频过渡的运动设计，而非软件内置文字特效菜单。
- [BCC Damaged TV Dissolve 官方文档](https://borisfx.com/documentation/continuum/bcc-damaged-tv-dissolve/)：CRT弱信号、滚屏、静电、干扰线、色差和分段缓动。转译为横向载波亮线→屏幕展开→正文信号锁定；退出先文字失活再压线关机。阅读期仅低幅扫描/颗粒，不循环故障冲击。
- [Split Transitions Pack](https://www.lookae.com/split-transitions-2/)：画面分割拆分转场。转译为背景板与内框反向遮罩展开，封签后扣，退出双向封套回收；不复制中文造成重影。
- [Lightspeed Transitions V2](https://www.lookae.com/lightspeed-transitions-v2/)：流畅运动、遮罩高光、缩放模糊和方向控制。转译为计分弹窗短冲击→回弹锁定→标签结算，并限制行程至字幕自身尺寸；正文保持清晰。
- [Libretro CRT](https://docs.libretro.com/shader/crt/)：扫描线、磷光遮罩和低幅滚动扫描。转译到字面和框内局部材质，不套全屏滤镜。

新组件 `version:5` 的 `typeEffect` 控制字面，`transition` 独立选择 `crt / score / foil`，可与既有框体、材质、关键词组合。所有运动使用工程时钟。`breathe + sustain:true + durationMs` 以真实毫秒节奏持续至阅读窗口终点；进退场压缩自身窗口，短句不把多轮阅读效果挤成闪烁。≤700ms极短句仍按宿主已定的稳定阅读策略显示。
