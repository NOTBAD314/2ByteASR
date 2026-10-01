# Noita 源像素动作研究与实现

2026-09-26。研究对象是机制，不复制商业插件代码、预设或素材。已读取官方文字说明和 GL Transitions 源码；未在本机运行 Sapphire/BCC/AE，也不声称观看了其完整商业示范视频。

## 来源与可迁移规则

|来源|读到的机制|本项目采用|没有照搬的部分|
|---|---|---|---|
|[Sapphire WipePixelate](https://borisfx.com/documentation/sapphire/ae/wipepixelate/)|块状空间显隐，边缘宽度控制混合区，频率/角度/块簇与固定种子控制图案|固定种子与块簇释放；显隐权重来自块在画面中的位置|只推进一条矩形擦除边缘不足以构成本轮主体动作|
|[Sapphire DissolveTiles](https://borisfx.com/documentation/sapphire/ae/dissolvetiles/)|源图瓦片位移，离开与进入图像可独立控制；方向和溶解延迟可分离|真实源图 RGBA 切片移动；位移、释放时间、透明度分别计算|不把缺失输入当成黑色背景；透明像素保持透明|
|[BCC 3D Image Shatter](https://borisfx.com/documentation/continuum/bcc-3d-image-shatter/)|碎片携带源纹理；梯度可规定先释放哪些碎片；速度、释放和重力独立|矿物块携真实字面；纵向位置与固定随机共同决定释放，解析重力轨迹|本实现是二维源像素位移，不声称三维碎片物理或完整 BCC 等效|
|[Adobe 文本动画与选择器](https://helpx.adobe.com/after-effects/desktop/animating-text/text-animation/animating-text.html#text_selectors)|选择器决定每个字符受影响的程度；范围、形状、随机顺序与随机幅度是不同概念；可按字符/词/行分组|将“分组权重/释放顺序”与“运动值”分离；固定种子保障 seek 可复现|不通过改源文本、复制正文或逐字符重排破坏现有排版|
|[GL randomsquares](https://github.com/gl-transitions/gl-transitions/blob/master/transitions/randomsquares.glsl)|基于网格坐标的稳定随机数与阈值显隐|稳定分组与无状态采样|原 shader 的反向 smoothstep 边界不作为可移植公式照搬|
|[GL pixelize](https://github.com/gl-transitions/gl-transitions/blob/master/transitions/pixelize.glsl)|采样网格中心，进度决定块大小，边界需要零值保护|设计像素格和输出像素量化、明确起止边界|不靠降低整张图分辨率替代主体碎片运动|
|[GL GridFlip](https://github.com/gl-transitions/gl-transitions/blob/master/transitions/GridFlip.glsl)|格子独立随机时序、空隙和中途翻转|借鉴空间单元独立释放|默认不透明背景与中点除法不适合透明字幕，未复制实现|

GL 源码按其 MIT 许可研究，原始文件与 LICENSE 的本轮下载位于 `tmp/rig-pixel-20260926`。当前共享运行时是独立 SVG SourceGraphic 实现，没有嵌入这些 shader。商业文档缓存也仅作为本地取证，不随安装包分发。

## 三组动作

- **炼金显形 / 像素余烬**：以局部邻域和固定随机秩组成像素簇。入场簇从短距离量化位移归位；退场原字框像素先变暖，再按风向上浮衰减。不是在原字框上额外撒粒子。
- **格块落位 / 矿物崩解**：每个大格保留自身源纹理，短落位带小幅回弹；退场以纵向位置与种子组合排序，位移使用线性初速度加二次重力项。
- **符印召唤 / 魔力回收**：字框区域分为多个邻域，按到左右锚点的距离和随机秩释放；入场从锚点展开，退场向锚点收束。既有法印最后熄灭。

三组均作用于 `.nt-read` 的真实字面及框面。v9 原样复用 v8 `cueHtml`、`cueCss`、`appearance`；仅替换进退场轨道。阅读态恢复 v8 的零 inset 裁剪边界，避免原本被裁掉的纹理越界；这不是动画擦除。读态滤镜撤销，源文本保持可编辑。

## 可编辑参数与时间

组件 `version:9` 可独立指定 `entryEffect` / `exitEffect`（alchemy、mineral、sigil），以及 `seed`、`blockSize`、`intensity`、`quality`。输出仍是普通完整 HTML/CSS/MotionSpec 档案。

MotionSpec 2 扩展 `pixels`，其进度轨必须为 `--pixel-progress:0→1`、`ease:none`、build/resolve、无重复或另一个 procedural 驱动。像素效果只接受具有布局尺寸的内部 HTML 容器。

运行时使用浏览器绘制的 SourceGraphic 做 alpha 切块，每个时间点的偏移/颜色/透明度都直接由同一个 cue 时间计算。由现有 paused GSAP timeline 的属性驱动器求值，没有新增 rAF、独立时钟或随机状态。原文不复制。每个分节内完整掩模只创建一次，逐帧只更新偏移及色矩阵。分组规模依画面与质量计算，不以固定 DOM 节点数决定美术合格。

不足 700ms 的 cue 沿用统一的稳定阅读态；1.5s 入口/出口时段沿用当前短 cue 调度。24fps末帧1458.33ms比30fps代理末帧1466.67ms更早：v9真实像素轨在resolve比例.52结束，附属轨最晚.55、法印最后结束，短cue最晚1455ms清空。补充验证同时检查24fps实际电影序列和30fps代理，不能仅检查cue结束时刻。HTML 是唯一源码，透明 PNG 代理仍是可丢弃的派生产物，runtime/字体/文案/时间/尺寸改变会使其失效。

## 验证边界

运行 `scripts/verify_pixel_caption.py --output tmp/<新目录>`：生产浏览器验证文字、长短句和1.5/6秒完整片段；检查反向 seek、读态与v8像素相等、最后编码帧 alpha、HTML档案重读、生产PNG代理一致性。

实际 UI 与压制导出另经普通 Studio 入口验证。渲染耗时不是实际呈现帧率；代理调用耗时不是显示器丢帧证据。本地程序产物明确标记 `local_fixture`，不能用来宣称新供应商请求成功。

启动器早期退出检查失败已定位为验收脚本给静态`QApplication.exec()`多传参数，触发原生错误框。修正脚本后4cue/4recipe打开与exit0通过，产品关闭代码未改，原失败记录保留。
