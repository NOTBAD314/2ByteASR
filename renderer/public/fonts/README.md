# 字幕主题的离线字体

这些是应用持有的字体，模型不能通过 CSS 选择任意文件。`webThemeFonts.ts` 与 Python `web_theme_fonts.py` 的映射一致；主文件在 `assets/fonts`，public 中的副本逐字节相同。

| 文件 | 来源 | 许可证 |
| --- | --- | --- |
| Cubic11.ttf | 用户本机已有 Cubic.ttf 原字节；[ACh-K/Cubic-11](https://github.com/ACh-K/Cubic-11) | Cubic11-OFL.txt（官方完整授权及上游声明） |
| SmileySans-Oblique.woff2 | atelier-anchor/smiley-sans，v2.0.1 原 WOFF2 | SmileySans-OFL.txt |
| ZCOOLKuaiLe-Regular.ttf | google/fonts，ofl/zcoolkuaile | ZCOOLKuaiLe-OFL.txt |
| ZCOOLQingKeHuangYou-Regular.ttf | google/fonts，ofl/zcoolqingkehuangyou | ZCOOLQingKeHuangYou-OFL.txt |
| SourceHanSansSC-Medium.woff2 | 仓库既有 Adobe Source Han Sans SC Medium OTF 的完整 WOFF2 封装 | SourceHanSansSC-OFL.txt |

思源黑体没有子集化或改字形；CFF、cmap、name、排版与度量表均与既有 OTF 字节一致，WOFF2 不携带原 DSIG。它只用于缺字回退。字体均随完整 OFL 许可证一起分发，不安装到用户系统。

2026-09-10 字体 SHA256：

```text
SmileySans-Oblique.woff2          731f22973349404b15a88a99ef3b5dd4104c0965c23b7e485c1f11e84fea99e2
ZCOOLKuaiLe-Regular.ttf          812a6fc1fe54b6d73a419245c32dfeba8aa33104d5be90d1cf6af082007cb71d
ZCOOLQingKeHuangYou-Regular.ttf  54f0c0df4308cd74cd0f2fd3494ae054dbc4a1fd6fa7d71f4807eb4cdd8b4136
SourceHanSansSC-Medium.woff2     c84123c18bf1f718ff6ce8a14b31cad916e8fe6ac509951bd172e272dca16215
```
