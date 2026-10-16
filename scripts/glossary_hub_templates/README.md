# 2ByteASR 线上词库

[2ByteASR（兔白字幕）](https://github.com/NOTBAD314/2ByteASR) 用户整理、维护者审核后发布的游戏术语库。在程序的「术语库」页点「线上词库」就能浏览、预览和安装，之后有新版本会提示更新。

- 中国大陆从 [GitCode 镜像](https://gitcode.com/Notbad314/2ByteASR-glossaries) 下载，海外从 GitHub 下载；不用翻墙。
- 程序只接受维护者签名过的目录，每个词库文件都按目录里的 SHA-256 校验。
- 安装后就是你自己的词库：你改过或删掉的词条，以后更新不会被覆盖。

## 词库里有什么

每条词是 `原词 → 结果`：

- **热词**（原词和结果相同，例如 `芙宁娜`）：只帮识别写对，不改字。
- **改字规则**（例如 `福宁娜 → 芙宁娜`）：字幕里出现左边的词，就改成右边。它会改所有出现的地方，所以只收常见误听，不收外号改官方名这类会改掉原话的规则。两字以内或普通词的规则，安装时默认不勾。

`verified_audio: true` 表示投稿人在实际直播的识别结果里见过这个误听。

## 投稿

在程序的术语库页选中你的词库，点「投稿」：

1. 程序先检查（冲突、超过 15 字、会改掉原话的规则等），只导出词和分类；理由、来源、任务编号和日期不会上传。
2. 程序导出文件，并打开 GitHub 或 GitCode 的 Issue 页面；标题和说明已复制好，把文件拖进去发布 Issue 即可。
3. 维护者审核后合并、签名、发布；大约下一次打开线上词库时就能看到。

也可以直接发 Pull Request：把文件放在 `libraries/<id>.json`，运行 `python tools/hub_check.py --libraries-only` 检查。

## 内容规则

- 只收游戏、直播相关的术语：角色、地点、技能、机制、道具、常见玩家用语和真实出现过的误听。
- 不收个人信息（真实姓名、联系方式、账号）、不收政治、色情、辱骂等内容。
- 发现问题请开 Issue，维护者会下架或修改。

## 授权

所有词库以 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hans) 发布：任何人都可以自由使用、修改、再发布，不需要署名。投稿即表示你同意以 CC0 公开你投稿的词条。

---

Community game glossaries for 2ByteASR, reviewed and signed by the maintainer, mirrored to GitCode for users in mainland China. Contributions are released under CC0 1.0.
