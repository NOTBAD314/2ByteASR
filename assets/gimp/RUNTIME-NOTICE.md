# GIMP 3.2.6 本地运行时来源与修改说明

本机从 [GIMP 官方 Windows 下载](https://www.gimp.org/downloads/)取得 `gimp-3.2.6-setup.exe`，校验 SHA256 与 Authenticode 后，按官方 Inno 安装脚本的 x64 组件和目标文件名提取。未修改官方 EXE/DLL/Python/插件，未执行全局安装器、注册文件关联或覆盖个人 GIMP 设置。排除 ARM64、开发文件和调试符号。逐文件清单在运行时根目录 `2byte-runtime-files.json`；固定来源和校验值见 `runtime.json`。

GIMP 以 GNU GPL 第 3 版或后续版本许可；完整许可见 `COPYING-GIMP.txt`。官方对应源码 `gimp-3.2.6.tar.xz` 随本机运行时放在 `source-and-licenses/`，包含构建脚本、Windows 依赖清单与补丁。官方源码入口为 [download.gimp.org/gimp/v3.2/](https://download.gimp.org/gimp/v3.2/)，上游仓库为 [GNOME/GIMP](https://gitlab.gnome.org/GNOME/gimp)。依赖的上游构建来源记载在该归档 `build/windows/`；GTK/GLib/GEGL/Babl、Python、图像编解码等仍按各自许可使用，原包包含的许可文件保持原位置。此交付是在同一台机器部署用户取得的官方运行时，没有发布第三方重打包下载站。

2ByteASR 新增的独立插件 `assets/gimp/2byte-cover-bridge.py` 以 GPL-3.0-or-later 提供完整源码，通过公开 GIMP PDB API 与宿主交互，不链接修改 GIMP 内部实现。宿主通过每会话受限本地文件队列管理应用创建的文档；不暴露网络控制端口。该插件和部署脚本均随应用可读源码提供。

应用专用字体来自项目已有 Source Han Sans SC Heavy，许可文件为 `assets/fonts/LICENSE.txt`（SIL OFL 1.1）。字体只复制到专用 GIMP profile/fonts，不安装进 Windows 或 Photoshop，也不声称 XCF/PSD 内嵌字体。

构建期提取工具 InnoUnp 2.71.1 来自 [作者维护的仓库](https://github.com/jrathlev/InnoUnpacker-Windows-GUI)，GPL v3；它不进入正常制作封面的执行链。原始官方安装器及校验记录在交付来源材料中保留。
