# Release checklist

## 每次发布必须遵守（2026-10-30，所有者要求）

GitCode（https://gitcode.com/Notbad314/2ByteASR）是必需的正式下载渠道。每次新版本先向 GitCode 上传更新档并核验，再向 GitHub 上传和公开；GitCode 失败时保留草稿、修复同步，不能跳过。安装包、更新组件、源码、许可、校验和签名两边保持相同字节；更新清单仍引用的旧组件也必须可下载。

1. 构建、安装/升级验收、源码和许可审查完成后，用 `feed --gitcode-first` 生成签名更新清单。先写版本说明，再开始上传。
2. 在 GitHub **只创建空草稿，不上传附件**：`gh release create vX.Y.Z --repo NOTBAD314/2ByteASR --draft --target <40位公开提交> --title "2ByteASR X.Y.Z" --notes-file docs/releases/X.Y.Z.md`。这一步供发布脚本取得标签与来源元数据。
3. 从完整的公开检出运行 `python -B scripts/release_pipeline.py gitcode --tag vX.Y.Z --assets <附件目录> --before-publish`，优先上传到 GitCode；必须匿名核验成功。该步骤暂不上传新更新清单和签名，并保持上一版 latest，避免程序提前发现未完成的版本。浅克隆先补齐公开历史；不要推开发工作区的私有历史。
4. GitCode 预传核验通过后，才运行下方 `upload` 上传 GitHub 草稿并执行 `verify-draft`；全部检查与当次发布授权满足后公开 GitHub。紧接着再次运行 `gitcode`（不带 `--before-publish`），补齐两个清单小文件、切换 latest 并匿名核验；再跑 GitHub `verify-public`。两站完成前不能报告发布完成。
5. 同步 GitCode 首页：基准是当时最新 GitHub 公开 main 的图文与资源，GitCode `README.md` 默认中文，英文保存为 `README_EN.md`，修正各语言入口；GitHub 保持自身默认语言。普通镜像命令会同步 main，**每次镜像后必须恢复并核验 GitCode 中文首页**，不能把它覆盖回英文。

Release 说明必须明确上一正式版本号，分别写“新增 / 改进 / 修正”，解释用户原先遇到什么、现在有什么变化；保留下载、升级方法、实际验证和已知限制，附 `compare/v<上一版>...v<本版>`。已有功能不能重复说成新增，未包含的开发日常不能写入已发布安装包的变化。没有某类变化就注明“无”，不要凑项目。优先让用户看到版本差异，再放技术验证细节。

本约定优先于下方历史步骤里“GitHub 发布后可选镜像”的说法，也不要求每次重新询问是否同步 GitCode。用户另行限定渠道的当次指令优先。

## 当前发布流程（2026-10-11 起，0.6.5）

全部在受控建置机上执行；签名私钥只在这台机器（`%USERPROFILE%\.2byteasr-release`，DPAPI 加密），从不进仓库、安装包或 CI。脚本拒绝覆盖已有输出，也拒绝替换已经公开的 Release 附件；修正一律走新版本号。

1. 改 `2byteasr_version.json` 的 `version`（stable 渠道 `channel: "stable"`），运行
   `python scripts/sync_product_version.py` 同步 EXE 版本资源与 renderer 版本。
2. `python -B scripts/release_pipeline.py freeze --version X.Y.Z --output tmp/release-XYZ/build-r1`
   ：固定快照 → PyInstaller → 编译 `2ByteASRUpdater.exe` → 写 `2byteasr_components.json` → 载荷扫描（只有已复核例外可放行）→ Build Truth → Setup。
3. `python -B scripts/release_pipeline.py feed --build <build> --assets releases/X.Y.Z --notes-json docs/releases/X.Y.Z.in-app.json --previous-manifest https://github.com/NOTBAD314/2ByteASR/releases/download/v<上一版>/2ByteASR-update.json`
   ：内容没变的元件直接引用上一版已公开的固定附件，只为变化的元件生成新包；生成并签名 `2ByteASR-update.json(.sig)`。
4. `python -B scripts/release_pipeline.py sources --build <build> --assets releases/X.Y.Z --review-commit <commit> --extra <固定第三方源码包>`，然后 `sums --assets releases/X.Y.Z`，再 `python -B scripts/release_signing.py sign --manifest releases/X.Y.Z/SHA256SUMS.txt` 生成 `SHA256SUMS.txt.sig`（同一把 Ed25519 密钥；`upload` 与两种核对会一并处理它）。
5. 用 `scripts/verify_release_install.py`（隔离 profile、AUDIT 安装）做全新安装、旧版覆盖升级、卸载；用 `scripts/qa_update_feed.py` 做只在本机的下一版更新与故障测试（渠道 `qa-local`，永不上传）。
6. `python -B scripts/release_public_tree.py --stage <build>/source --base origin/main --branch release/vX.Y.Z ...`：以公开线为父提交、只更新程序源码路径，并扫描密钥/个人路径；文件按原始字节写入（不经开发目录的 `.gitattributes` 换行转换）。推送前运行 `python -B scripts/release_pipeline.py verify-source --build <build> --commit <release commit>`，干净检出必须逐字节重现构建源码指纹（0.6.5 的第一个发布提交 `f9b2ea71` 因换行被转换而未通过，已由 `a74c6d64` 纠正）；`git push origin release/vX.Y.Z`（提交信息带 `[skip ci]`）。
7. `python -B scripts/release_pipeline.py upload --assets releases/X.Y.Z --tag vX.Y.Z --target <release commit> --title ... --notes-file docs/releases/X.Y.Z.md`
   ：建立**草稿**并上传，逐件核对大小与服务端 SHA-256，认证读回小文件。中途失败就原样重跑：已上传且一致的附件会跳过，不一致的拒绝替换。
   若之后要改草稿说明，用 API 修改时必须同时带上 `tag_name` 与 `target_commitish`（只改 body 会让 GitHub 把草稿的 tag 清成 `untagged-…`，0.6.5 实际遇到过），改完再跑一次 `verify-draft`。
8. 所有者检查后手动 Publish。之后运行 `python -B scripts/release_pipeline.py verify-public --tag vX.Y.Z --assets releases/X.Y.Z`（不带任何凭据），或在 GitHub Actions 手动运行 `verify-public-release`，确认 Setup、更新清单及其引用的全部附件都能匿名下载。

`.github/workflows/release.yml` 不再在推送 tag 时构建或创建 Release，只做手动匿名校验。仓库仍为私有时，匿名下载必然失败；这不是发布脚本的问题。

公开门：`licenses/DISTRIBUTION-STATUS.md`、`licenses/GPL3_ROUTE.md` 所列对应源码与第三方组合权利问题未关闭前，不应把二进制宣称为已满足公开分发条件。

## 旧流程（历史记录，勿再使用）

2026-09-29 的冻结流程已被上面的流程取代；下方 `build_installer.ps1` / tag CI 是更早的源码式流程。

## Before the first public push

1. Choose the final GitHub owner, repository name, visibility, description, and topics.
2. Review `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `SECURITY.md` with the repository owner identity filled in where appropriate.
3. Run the offline checks:

   ```powershell
   .\.venv-main\Scripts\python.exe -m pytest -q tests
   .\.venv-main\Scripts\python.exe scripts\check_release_hygiene.py
   ```

4. Inspect the exact Git candidate set before committing:

   ```powershell
   git status --short
   git ls-files --others --exclude-standard
   ```

The model weights, virtual environments, third-party checkouts, media, reports, backups, generated binaries, and installer output must remain ignored.

## Build a local installer

Install Inno Setup 6, then run:

```powershell
.\scripts\build_installer.ps1 -Version 0.1.0
```

The result is `dist\2ByteASR-Setup-0.1.0.exe`. The build script prints its SHA-256 digest.

## Publish a release

After the main branch has been pushed and CI is green:

```powershell
git tag -a v0.1.0 -m "2ByteASR 0.1.0"
git push origin main
git push origin v0.1.0
```

The `build-release-installer` workflow reruns tests on Windows, builds the installer, and attaches it to a GitHub Release.

For routine updates, increment only the patch version and keep the installer `AppId`, install directory, and unchanged model revisions stable. Users should install over the previous version rather than uninstalling it. See [UPDATING.md](UPDATING.md) for the preservation and model-download rules.

## Code signing

Without a certificate, the installer and launcher are unsigned and Windows SmartScreen may warn users. When a code-signing certificate is installed in the current user's certificate store and the Windows SDK `signtool.exe` is available, build with its 40-character SHA-1 thumbprint:

```powershell
.\scripts\build_installer.ps1 -Version 0.1.0 -SignThumbprint "<certificate-thumbprint>"
```

The build signs the installer and generated uninstaller with SHA-256, adds an HTTPS timestamp, then verifies the installer signature. Do not place a signing certificate or password in the repository; use a protected release environment or an external signing service.

## Release notes

Every release should state:

- supported Windows and GPU requirements;
- that first-time setup downloads pinned models (~7 GB by default, ~11.7 GB with the optional Qwen reviewer);
- whether the executables are signed;
- cloud text-processing behavior and the configured provider;
- noteworthy compatibility or model changes.
