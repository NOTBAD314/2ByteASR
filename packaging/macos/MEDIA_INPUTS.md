# macOS 媒体输入：2026-10-02 功能修订

原锁标准 ffmpeg9.0.2_0 的实际搬移包在 run36969434185 压制时报告 No such filter: ass。Studio编辑保存与四格式字幕回读均通过，这个失败属于媒体功能输入，不是模型或字幕文件失败。

本次选定仍是官方 homebrew-core commit 0211e9c2eeea26bc0f1b382446dc076321e9a871，macOS15 arm64_sequoia；仅将逻辑 ffmpeg 输入切换到同一版本9.0.2/revision0的 keg-only ffmpeg-full。mpv0.41.0/revision10不变。不是滚动latest或现场回填版本。

- [固定官方full配方](https://github.com/Homebrew/homebrew-core/blob/0211e9c2eeea26bc0f1b382446dc076321e9a871/Formula/f/ffmpeg-full.rb)，配方SHA256 9d97328f2cc181719a6bc15982e3706f5c6ce39a2d959c96e40ccde503c81056。
- 目标bottle归档SHA256 ef9633f1fee8a0039c6b8ac241f6303c2d4768892f2e84a4934564e91e9fff90，原标准bottle为 c8006779a2919e921e66bbdbf2aa5c989acc5f3626884ec725e58e161f5e843f。
- full配方明确 --enable-libass，依赖libass/fontconfig/freetype等；上游配方声明FFmpeg组合为GPL-3.0-or-later，保持该第三方范围，项目自身GPL-3.0-only不变。这份输入声明不表示内部实验二进制已取得公开发行的全部对应源码。
- Homebrew从固定core处理bottle依赖、安装receipt和重定位。保留标准ffmpeg及其他runner工具；不给keg-only工具全局force-link。取得脚本的私有PATH先选准确full keg，封存实际路径/摘要；打包脚本随后只使用该回执。
- PyInstaller 6.22.2 会排序显式输入并对同目的名保留首条库；mpv 的标准FFmpeg依赖与full库同名。spec显式收集已选full keg dylib，让它们先于自动发现的标准依赖；仍须在真实ZIP解压后、最小PATH环境枚举包内滤镜，不能只靠执行文件排序声明成功。
- 必需滤镜ass/subtitles/overlay/scale/trim/concat/amix在昂贵模型准备前由准确可执行文件真实枚举，打包入口再核对；缺失、错误摘要/版本/架构均失败。归档SHA与可执行SHA分别取证，不互相冒充。

真实本轮状态见[macOS验证说明](../../docs/deployment/macos-validation.zh-CN.md)；full锁的原生验收结果在最终CI回执中单列，不继承前版结果。

第五场36971433917已取得上述准确full bottle并记录arm64 FFmpeg9.0.2真实执行；自有滤镜解析器错误要求三列标志，误拒绝实际两列，未生成full应用。解析兼容修正已在本地用完整原生输出回放验证，未新原生运行。包内full库/滤镜/视频效果仍未验，不能把第四场标准媒体app的通过项移植到这份锁上。

2026-10-02续测36973039995/61ee0118已原生核对full取得/安装身份、选定full dylib打包、Unicode搬移后的实际FFmpeg滤镜与12秒/360帧ASS中文字幕音视频导出全解码。归档、receipt、执行与打包后SHA各自单列，重定位/ad hoc签名改变包内字节，不能拿bottle摘要比执行文件。实际Studio整窗抓图黑色另需验证，不能以该媒体成功代替Qt画布验收。第二场e0e8c5ce加入该像素门，尚在运行。无公开安装包/对应源码发行放行。


2026-10-02续测最终：run36975908980/source及workflow cfe9b13d固定取得/归档SHA/实际keg及receipt revision/精确执行路径/文件SHA/arm64/运行版本、full动态库打包、Unicode搬移后包内滤镜全部通过；实际12秒360帧中文字幕与AAC导出全解码通过。没有更新锁为latest或抄实际值回预期。实际Studio四处Qt画面亦通过，绘制修复不修改媒体锁或归档摘要。三场均独立attempt1，原始失败与应用保留。
