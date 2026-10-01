# 实际发行组件与许可材料目录

当前许可路线更新见 [GPL3_ROUTE.md](GPL3_ROUTE.md)。以下基线版本证据保留，不将旧包清单当作新候选逐文件验证。

版权字段仅展示可定位到组件专属授权前言或核对过的源文件头的声明，不代表穷尽全部权利人。通用许可起草者、字体例外和条约句子不作为组件权利人；未核实项保留状态，完整原文不裁剪。

基于品牌Setup `0d2796a1…c88878c`。本目录记录新补到源码树的材料，不表示旧Setup已含这些文件，也不代表发行兼容性已获批准。604条为分层记录，含重复依赖及未查明原生库。各项保持原审计证据等级。

A＝随源码分发；B＝实际Setup载荷（含离线wheel/实际附带开发包）；C＝首次准备下载；D＝用户另配；E＝仅开发。自有代码现采用GPL-3.0-only；独立第三方许可不变，旧禁售目标已经撤销。

原文完整内容/版权/NOTICE保留于链接文件；只有元数据的记录不提升为许可核实。源码与构建义务见[SOURCES.md](SOURCES.md)，模型见[MODELS.md](MODELS.md)，机器回执见[component-index.json](component-index.json)。

## 1. @babel/code-frame — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/code-frame`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fcode-frame/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/code-frame/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_code-frame-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 2. @babel/compat-data — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/compat-data`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fcompat-data/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/compat-data/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_compat-data-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 3. @babel/core — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/core`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fcore/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/core/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_core-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 4. @babel/parser — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/core/node_modules/@babel/parser`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2014 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fparser/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/core/node_modules/@babel/parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_parser-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 5. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/core/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/core/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 6. semver — 6.3.1

- 范围/位置：B；`renderer/node_modules/@babel/core/node_modules/semver`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/semver/6.3.1)；[对应来源](https://github.com/npm/node-semver.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/core/node_modules/semver/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/semver-6.3.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 7. @babel/generator — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/generator`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fgenerator/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/generator/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_generator-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 8. @babel/parser — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/generator/node_modules/@babel/parser`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2014 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fparser/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/generator/node_modules/@babel/parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_parser-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 9. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/generator/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/generator/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 10. @babel/helper-compilation-targets — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-compilation-targets`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-compilation-targets/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-compilation-targets/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-compilation-targets-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 11. semver — 6.3.1

- 范围/位置：B；`renderer/node_modules/@babel/helper-compilation-targets/node_modules/semver`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/semver/6.3.1)；[对应来源](https://github.com/npm/node-semver.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-compilation-targets/node_modules/semver/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/semver-6.3.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 12. @babel/helper-globals — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-globals`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-globals/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-globals/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-globals-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 13. @babel/helper-module-imports — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-module-imports`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-module-imports/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-module-imports/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-module-imports-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 14. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/helper-module-imports/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-module-imports/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 15. @babel/helper-module-transforms — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-module-transforms`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-module-transforms/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-module-transforms/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-module-transforms-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 16. @babel/helper-string-parser — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-string-parser`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-string-parser/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-string-parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-string-parser-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 17. @babel/helper-validator-identifier — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-validator-identifier`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-validator-identifier/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-validator-identifier/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-validator-identifier-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 18. @babel/helper-validator-option — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helper-validator-option`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelper-validator-option/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helper-validator-option/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helper-validator-option-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 19. @babel/helpers — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/helpers`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors；Copyright (c) 2014-present, Facebook, Inc. (ONLY ./src/helpers/regenerator* files)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fhelpers/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helpers/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_helpers-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 20. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/helpers/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/helpers/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 21. @babel/parser — 7.24.1

- 范围/位置：B；`renderer/node_modules/@babel/parser`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2014 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fparser/7.24.1)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_parser-7.24.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 22. @babel/template — 7.29.7

- 范围/位置：B；`renderer/node_modules/@babel/template`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftemplate/7.29.7)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/template/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_template-7.29.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 23. @babel/parser — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/template/node_modules/@babel/parser`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2014 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fparser/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/template/node_modules/@babel/parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_parser-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 24. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/template/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/template/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 25. @babel/traverse — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/traverse`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftraverse/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/traverse/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_traverse-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 26. @babel/parser — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/traverse/node_modules/@babel/parser`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2014 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Fparser/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/traverse/node_modules/@babel/parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_parser-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 27. @babel/types — 7.29.8

- 范围/位置：B；`renderer/node_modules/@babel/traverse/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.29.8)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/traverse/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.29.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 28. @babel/types — 7.24.0

- 范围/位置：B；`renderer/node_modules/@babel/types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-present Sebastian McKenzie and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/@babel%2Ftypes/7.24.0)；[对应来源](https://github.com/babel/babel.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@babel/types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/babel_types-7.24.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 29. @esbuild/win32-x64 — 0.28.1

- 范围/位置：B；`renderer/node_modules/@esbuild/win32-x64`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Evan Wallace。
- 来源：[对应来源](https://registry.npmjs.org/@esbuild%2Fwin32-x64/0.28.1)；[对应来源](https://github.com/evanw/esbuild.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@esbuild/win32-x64/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/esbuild-0.28.1/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E；许可取自同版本esbuild主包；保留平台二进制来源与独立修改状态核查。。

## 30. @jridgewell/gen-mapping — 0.3.13

- 范围/位置：B；`renderer/node_modules/@jridgewell/gen-mapping`。
- 许可：MIT。组件版权声明：Copyright 2024 Justin Ridgewell <justin@ridgewell.name>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Fgen-mapping/0.3.13)；[对应来源](https://github.com/jridgewell/sourcemaps.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/gen-mapping/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_gen-mapping-0.3.13/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 31. @jridgewell/remapping — 2.3.5

- 范围/位置：B；`renderer/node_modules/@jridgewell/remapping`。
- 许可：MIT。组件版权声明：Copyright 2024 Justin Ridgewell <justin@ridgewell.name>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Fremapping/2.3.5)；[对应来源](https://github.com/jridgewell/sourcemaps.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/remapping/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_remapping-2.3.5/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 32. @jridgewell/resolve-uri — 3.1.2

- 范围/位置：B；`renderer/node_modules/@jridgewell/resolve-uri`。
- 许可：MIT。组件版权声明：Copyright 2019 Justin Ridgewell <jridgewell@google.com>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Fresolve-uri/3.1.2)；[对应来源](https://github.com/jridgewell/resolve-uri)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/resolve-uri/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_resolve-uri-3.1.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 33. @jridgewell/source-map — 0.3.11

- 范围/位置：B；`renderer/node_modules/@jridgewell/source-map`。
- 许可：MIT。组件版权声明：Copyright 2024 Justin Ridgewell <justin@ridgewell.name>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Fsource-map/0.3.11)；[对应来源](https://github.com/jridgewell/sourcemaps.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/source-map/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_source-map-0.3.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 34. @jridgewell/sourcemap-codec — 1.5.5

- 范围/位置：B；`renderer/node_modules/@jridgewell/sourcemap-codec`。
- 许可：MIT。组件版权声明：Copyright 2024 Justin Ridgewell <justin@ridgewell.name>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Fsourcemap-codec/1.5.5)；[对应来源](https://github.com/jridgewell/sourcemaps.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/sourcemap-codec/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_sourcemap-codec-1.5.5/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 35. @jridgewell/trace-mapping — 0.3.31

- 范围/位置：B；`renderer/node_modules/@jridgewell/trace-mapping`。
- 许可：MIT。组件版权声明：Copyright 2024 Justin Ridgewell <justin@ridgewell.name>。
- 来源：[对应来源](https://registry.npmjs.org/@jridgewell%2Ftrace-mapping/0.3.31)；[对应来源](https://github.com/jridgewell/sourcemaps.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@jridgewell/trace-mapping/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jridgewell_trace-mapping-0.3.31/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 36. @mediabunny/aac-encoder — 1.50.8

- 范围/位置：B；`renderer/node_modules/@mediabunny/aac-encoder`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@mediabunny%2Faac-encoder/1.50.8)；[对应来源](https://github.com/Vanilagy/mediabunny.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@mediabunny/aac-encoder/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mediabunny_aac-encoder-1.50.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 37. @mediabunny/flac-encoder — 1.50.8

- 范围/位置：B；`renderer/node_modules/@mediabunny/flac-encoder`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@mediabunny%2Fflac-encoder/1.50.8)；[对应来源](https://github.com/Vanilagy/mediabunny.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@mediabunny/flac-encoder/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mediabunny_flac-encoder-1.50.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 38. @mediabunny/mp3-encoder — 1.50.8

- 范围/位置：B；`renderer/node_modules/@mediabunny/mp3-encoder`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@mediabunny%2Fmp3-encoder/1.50.8)；[对应来源](https://github.com/Vanilagy/mediabunny.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@mediabunny/mp3-encoder/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mediabunny_mp3-encoder-1.50.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 39. @module-federation/error-codes — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/error-codes`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 ScriptedAlchemy LLC (Zack Jackson) Zhou Shaw (zhouxiao)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Ferror-codes/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/error-codes/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_error-codes-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 40. @module-federation/runtime — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/runtime`。
- 许可：MIT。组件版权声明：Copyright (c) 2023-present zhouxiao(zhoushaw)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Fruntime/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/runtime/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_runtime-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 41. @module-federation/runtime-core — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/runtime-core`。
- 许可：MIT。组件版权声明：Copyright (c) 2023-present zhouxiao(zhoushaw)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Fruntime-core/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/runtime-core/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_runtime-core-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 42. @module-federation/runtime-tools — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/runtime-tools`。
- 许可：MIT。组件版权声明：Copyright (c) 2023-present zhouxiao(zhoushaw)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Fruntime-tools/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/runtime-tools/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_runtime-tools-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 43. @module-federation/sdk — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/sdk`。
- 许可：MIT。组件版权声明：Copyright (c) 2023-present zhanghang(2heal1)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Fsdk/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/sdk/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_sdk-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 44. @module-federation/webpack-bundler-runtime — 0.22.0

- 范围/位置：B；`renderer/node_modules/@module-federation/webpack-bundler-runtime`。
- 许可：MIT。组件版权声明：Copyright (c) 2023-present zhanghang(2heal1)。
- 来源：[对应来源](https://registry.npmjs.org/@module-federation%2Fwebpack-bundler-runtime/0.22.0)；[对应来源](https://github.com/module-federation/core.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@module-federation/webpack-bundler-runtime/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/module-federation_webpack-bundler-runtime-0.22.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 45. @remotion/bundler — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/bundler`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fbundler/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/bundler)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/bundler/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_bundler-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 46. @remotion/captions — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/captions`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fcaptions/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/captions)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/captions/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 47. @remotion/cli — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/cli`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fcli/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/cli)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/cli/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_cli-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 48. @remotion/compositor-win32-x64-msvc — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/compositor-win32-x64-msvc`。
- 许可：元数据缺许可证。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fcompositor-win32-x64-msvc/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/compositor-win32-x64-msvc)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/compositor-win32-x64-msvc/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)；[config.yml](source-materials/remotion-4.0.513/splitter/.circleci/config.yml)；[build.yml](source-materials/remotion-4.0.513/splitter/.github/workflows/build.yml)；[Cargo.lock](source-materials/remotion-4.0.513/splitter/Cargo.lock)；[Cargo.toml](source-materials/remotion-4.0.513/splitter/Cargo.toml)；[Dockerfile](source-materials/remotion-4.0.513/splitter/Dockerfile)；[Dockerfile-aws](source-materials/remotion-4.0.513/splitter/Dockerfile-aws)；[README.md](source-materials/remotion-4.0.513/splitter/README.md)；[aac.patch](source-materials/remotion-4.0.513/splitter/aac.patch)；[build.rs](source-materials/remotion-4.0.513/splitter/build.rs)；[clean.mjs](source-materials/remotion-4.0.513/splitter/clean.mjs)；[compile-av1.mjs](source-materials/remotion-4.0.513/splitter/compile-av1.mjs)；[compile-fdkaac.mjs](source-materials/remotion-4.0.513/splitter/compile-fdkaac.mjs)；[compile-ffmpeg.mjs](source-materials/remotion-4.0.513/splitter/compile-ffmpeg.mjs)；[compile-libmp3lame.mjs](source-materials/remotion-4.0.513/splitter/compile-libmp3lame.mjs)；[compile-nvenc.mjs](source-materials/remotion-4.0.513/splitter/compile-nvenc.mjs)；[compile-opus.mjs](source-materials/remotion-4.0.513/splitter/compile-opus.mjs)；[compile-vpx.mjs](source-materials/remotion-4.0.513/splitter/compile-vpx.mjs)；[compile-x264.mjs](source-materials/remotion-4.0.513/splitter/compile-x264.mjs)；[compile-x265.mjs](source-materials/remotion-4.0.513/splitter/compile-x265.mjs)；[compile-zimg.mjs](source-materials/remotion-4.0.513/splitter/compile-zimg.mjs)；[const.mjs](source-materials/remotion-4.0.513/splitter/const.mjs)；[fdk-aac-free.patch](source-materials/remotion-4.0.513/splitter/fdk-aac-free.patch)；[fix-links.mjs](source-materials/remotion-4.0.513/splitter/fix-links.mjs)；[fix-linux-links.mjs](source-materials/remotion-4.0.513/splitter/fix-linux-links.mjs)；[get-from-docker.mjs](source-materials/remotion-4.0.513/splitter/get-from-docker.mjs)；[hevc_ps.patch](source-materials/remotion-4.0.513/splitter/hevc_ps.patch)；[main.rs](source-materials/remotion-4.0.513/splitter/main.rs)；[x265-api.patch](source-materials/remotion-4.0.513/splitter/x265-api.patch)；[zip.mjs](source-materials/remotion-4.0.513/splitter/zip.mjs)；[sys-SOURCE.md](source-materials/remotion-4.0.513/sys-SOURCE.md)；[remotion-Cargo.lock](source-materials/remotion-4.0.513/remotion-Cargo.lock)；[remotion-Cargo.toml](source-materials/remotion-4.0.513/remotion-Cargo.toml)；[remotion-compositor-build.ts](source-materials/remotion-4.0.513/remotion-compositor-build.ts)；[remotion-ffmpeg-license.mdx](source-materials/remotion-4.0.513/remotion-ffmpeg-license.mdx)；[ffmpeg-7.1.tar.xz](source-materials/remotion-4.0.513/ffmpeg-7.1.tar.xz)；[x265-419182243-source.tar.gz](source-materials/remotion-4.0.513/x265-419182243-source.tar.gz)；[x265-419182243-COPYING.txt](source-materials/remotion-4.0.513/x265-419182243-COPYING.txt)；[x264-source.tar.bz2](source-materials/pyav-17.1.0/x264-source.tar.bz2)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E；compositor实际avcodec内嵌x264 r3222 b35605a、x265 3.4+28-419182243；对应基础源码已补，Windows预编译库构建参数/补丁与fdk-aac-free原文尚未闭合；不能与PyAV的x264矛盾混写。。

## 49. @remotion/licensing — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/licensing`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Flicensing/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/licensing)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/licensing/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 50. @remotion/media-parser — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/media-parser`。
- 许可：Remotion License https://remotion.dev/license。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fmedia-parser/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/media-parser)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/media-parser/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 51. @remotion/media-utils — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/media-utils`。
- 许可：MIT。组件版权声明：Copyright (c) 2021 JonnyBurger；Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fmedia-utils/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/media-utils)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/media-utils/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_media-utils-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 52. @remotion/player — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/player`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fplayer/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/player)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/player/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_player-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 53. @remotion/renderer — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/renderer`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Frenderer/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/renderer)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/renderer/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_renderer-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 54. @remotion/streaming — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/streaming`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstreaming/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/streaming)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/streaming/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 55. @remotion/studio — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/studio`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstudio/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/studio)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/studio/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 56. @remotion/studio-codemods — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/studio-codemods`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstudio-codemods/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/studio-codemods)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/studio-codemods/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 57. @remotion/studio-protocol — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/studio-protocol`。
- 许可：Remotion License。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstudio-protocol/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/studio-protocol)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/studio-protocol/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 58. @remotion/studio-server — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/studio-server`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstudio-server/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/studio-server)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/studio-server/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 59. @remotion/studio-shared — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/studio-shared`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fstudio-shared/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/studio-shared)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/studio-shared/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 60. @remotion/timeline-utils — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/timeline-utils`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Ftimeline-utils/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/timeline-utils)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/timeline-utils/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 61. @remotion/web-renderer — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/web-renderer`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fweb-renderer/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/web-renderer)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/web-renderer/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion_web-renderer-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 62. @remotion/zod-types — 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/zod-types`。
- 许可：MIT。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/@remotion%2Fzod-types/4.0.513)；[对应来源](https://github.com/remotion-dev/remotion/tree/main/packages/zod-types)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@remotion/zod-types/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 63. @rspack/binding — 1.7.11

- 范围/位置：B；`renderer/node_modules/@rspack/binding`。
- 许可：MIT。组件版权声明：Copyright (c) 2022-present Bytedance, Inc. and its affiliates.。
- 来源：[对应来源](https://registry.npmjs.org/@rspack%2Fbinding/1.7.11)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/binding/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/rspack_binding-1.7.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 64. @rspack/binding-win32-x64-msvc — 1.7.11

- 范围/位置：B；`renderer/node_modules/@rspack/binding-win32-x64-msvc`。
- 许可：MIT。组件版权声明：Copyright (c) 2022-present Bytedance Inc and its affiliates.。
- 来源：[对应来源](https://registry.npmjs.org/@rspack%2Fbinding-win32-x64-msvc/1.7.11)；[对应来源](https://github.com/web-infra-dev/rspack)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/binding-win32-x64-msvc/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/rspack_binding-win32-x64-msvc-1.7.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 65. @rspack/core — 1.7.11

- 范围/位置：B；`renderer/node_modules/@rspack/core`。
- 许可：MIT。组件版权声明：Copyright (c) 2022-present Bytedance, Inc. and its affiliates.。
- 来源：[对应来源](https://registry.npmjs.org/@rspack%2Fcore/1.7.11)；[对应来源](https://github.com/web-infra-dev/rspack)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/rspack_core-1.7.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 66. @swc/types — 0.1.25

- 范围/位置：B；`renderer/node_modules/@rspack/core/compiled/@swc/types`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@swc%2Ftypes/0.1.25)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/compiled/@swc/types/package.json`。
- 完整原文及现有材料：[license](materials/npm/swc_types-0.1.25/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 67. browserslist-load-config — 1.0.1

- 范围/位置：B；`renderer/node_modules/@rspack/core/compiled/browserslist-load-config`。
- 许可：MIT。组件版权声明：Copyright (c) 2024 Rspack Contrib。
- 来源：[对应来源](https://registry.npmjs.org/browserslist-load-config/1.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/compiled/browserslist-load-config/package.json`。
- 完整原文及现有材料：[license](materials/npm/browserslist-load-config-1.0.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 68. tinypool — 1.1.1

- 范围/位置：B；`renderer/node_modules/@rspack/core/compiled/tinypool`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 James M Snell and the Piscina contributors。
- 来源：[对应来源](https://registry.npmjs.org/tinypool/1.1.1)；[对应来源](https://github.com/tinylibs/tinypool.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/compiled/tinypool/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/tinypool-1.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 69. watchpack — 2.4.4

- 范围/位置：B；`renderer/node_modules/@rspack/core/compiled/watchpack`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/watchpack/2.4.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/compiled/watchpack/package.json`。
- 完整原文及现有材料：[license](materials/npm/watchpack-2.4.4/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 70. webpack-sources — 3.3.3

- 范围/位置：B；`renderer/node_modules/@rspack/core/compiled/webpack-sources`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 JS Foundation and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/webpack-sources/3.3.3)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/core/compiled/webpack-sources/package.json`。
- 完整原文及现有材料：[license](materials/npm/webpack-sources-3.3.3/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 71. @rspack/lite-tapable — 1.1.0

- 范围/位置：B；`renderer/node_modules/@rspack/lite-tapable`。
- 许可：MIT。组件版权声明：Copyright (c) 2022-present Bytedance, Inc. and its affiliates.。
- 来源：[对应来源](https://registry.npmjs.org/@rspack%2Flite-tapable/1.1.0)；[对应来源](https://github.com/rspack-contrib/rspack-lite-tapable)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/lite-tapable/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/rspack_lite-tapable-1.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 72. @rspack/plugin-react-refresh — 1.6.1

- 范围/位置：B；`renderer/node_modules/@rspack/plugin-react-refresh`。
- 许可：MIT。组件版权声明：Copyright (c) 2022-present Bytedance, Inc. and its affiliates.。
- 来源：[对应来源](https://registry.npmjs.org/@rspack%2Fplugin-react-refresh/1.6.1)；[对应来源](https://github.com/rstackjs/rspack-plugin-react-refresh)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@rspack/plugin-react-refresh/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/rspack_plugin-react-refresh-1.6.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 73. @svgr/babel-plugin-add-jsx-attribute — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-add-jsx-attribute`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-add-jsx-attribute/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-add-jsx-attribute)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-add-jsx-attribute/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-add-jsx-attribute-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 74. @svgr/babel-plugin-remove-jsx-attribute — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-remove-jsx-attribute`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-remove-jsx-attribute/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-remove-jsx-attribute)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-remove-jsx-attribute/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-remove-jsx-attribute-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 75. @svgr/babel-plugin-remove-jsx-empty-expression — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-remove-jsx-empty-expression`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-remove-jsx-empty-expression/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-remove-jsx-empty-expression)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-remove-jsx-empty-expression/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-remove-jsx-empty-expression-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 76. @svgr/babel-plugin-replace-jsx-attribute-value — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-replace-jsx-attribute-value`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-replace-jsx-attribute-value/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-replace-jsx-attribute-value)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-replace-jsx-attribute-value/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-replace-jsx-attribute-value-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 77. @svgr/babel-plugin-svg-dynamic-title — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-svg-dynamic-title`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-svg-dynamic-title/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-svg-dynamic-title)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-svg-dynamic-title/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-svg-dynamic-title-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 78. @svgr/babel-plugin-svg-em-dimensions — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-svg-em-dimensions`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-svg-em-dimensions/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-svg-em-dimensions)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-svg-em-dimensions/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-svg-em-dimensions-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 79. @svgr/babel-plugin-transform-react-native-svg — 8.1.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-transform-react-native-svg`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-transform-react-native-svg/8.1.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-transform-react-native-svg)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-transform-react-native-svg/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-transform-react-native-svg-8.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 80. @svgr/babel-plugin-transform-svg-component — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-plugin-transform-svg-component`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-plugin-transform-svg-component/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-plugin-transform-svg-component)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-plugin-transform-svg-component/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-plugin-transform-svg-component-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 81. @svgr/babel-preset — 8.1.0

- 范围/位置：B；`renderer/node_modules/@svgr/babel-preset`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fbabel-preset/8.1.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/babel-preset)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/babel-preset/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_babel-preset-8.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 82. @svgr/core — 8.1.0

- 范围/位置：B；`renderer/node_modules/@svgr/core`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fcore/8.1.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/core)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/core/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_core-8.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 83. @svgr/hast-util-to-babel-ast — 8.0.0

- 范围/位置：B；`renderer/node_modules/@svgr/hast-util-to-babel-ast`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fhast-util-to-babel-ast/8.0.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/hast-util-to-babel-ast)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/hast-util-to-babel-ast/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_hast-util-to-babel-ast-8.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 84. @svgr/plugin-jsx — 8.1.0

- 范围/位置：B；`renderer/node_modules/@svgr/plugin-jsx`。
- 许可：MIT。组件版权声明：Copyright 2017 Smooth Code。
- 来源：[对应来源](https://registry.npmjs.org/@svgr%2Fplugin-jsx/8.1.0)；[对应来源](https://github.com/gregberge/svgr/tree/main/packages/plugin-jsx)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@svgr/plugin-jsx/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/svgr_plugin-jsx-8.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 85. @types/dom-mediacapture-transform — 0.1.12

- 范围/位置：B；`renderer/node_modules/@types/dom-mediacapture-transform`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Fdom-mediacapture-transform/0.1.12)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/dom-mediacapture-transform/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_dom-mediacapture-transform-0.1.12/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 86. @types/dom-webcodecs — 0.1.13

- 范围/位置：B；`renderer/node_modules/@types/dom-webcodecs`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Fdom-webcodecs/0.1.13)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/dom-webcodecs/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_dom-webcodecs-0.1.13/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 87. @types/eslint — 9.6.1

- 范围/位置：B；`renderer/node_modules/@types/eslint`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Feslint/9.6.1)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/eslint/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_eslint-9.6.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 88. @types/eslint-scope — 3.7.7

- 范围/位置：B；`renderer/node_modules/@types/eslint-scope`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Feslint-scope/3.7.7)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/eslint-scope/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_eslint-scope-3.7.7/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 89. @types/estree — 1.0.9

- 范围/位置：B；`renderer/node_modules/@types/estree`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Festree/1.0.9)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/estree/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_estree-1.0.9/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 90. @types/json-schema — 7.0.15

- 范围/位置：B；`renderer/node_modules/@types/json-schema`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Fjson-schema/7.0.15)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/json-schema/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_json-schema-7.0.15/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 91. @types/node — 26.2.0

- 范围/位置：B；`renderer/node_modules/@types/node`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Fnode/26.2.0)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/node/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_node-26.2.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 92. @types/react — 19.2.18

- 范围/位置：B；`renderer/node_modules/@types/react`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@types%2Freact/19.2.18)；[对应来源](https://github.com/DefinitelyTyped/DefinitelyTyped.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@types/react/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/types_react-19.2.18/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 93. @webassemblyjs/ast — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/ast`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fast/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/ast/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_ast-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 94. @webassemblyjs/floating-point-hex-parser — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/floating-point-hex-parser`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Mauro Bringolf。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Ffloating-point-hex-parser/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/floating-point-hex-parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_floating-point-hex-parser-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 95. @webassemblyjs/helper-api-error — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/helper-api-error`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fhelper-api-error/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/helper-api-error/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_helper-api-error-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 96. @webassemblyjs/helper-buffer — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/helper-buffer`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fhelper-buffer/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/helper-buffer/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_helper-buffer-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 97. @webassemblyjs/helper-numbers — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/helper-numbers`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fhelper-numbers/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/helper-numbers/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_helper-numbers-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 98. @webassemblyjs/helper-wasm-bytecode — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/helper-wasm-bytecode`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fhelper-wasm-bytecode/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/helper-wasm-bytecode/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_helper-wasm-bytecode-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 99. @webassemblyjs/helper-wasm-section — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/helper-wasm-section`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fhelper-wasm-section/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/helper-wasm-section/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_helper-wasm-section-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 100. @webassemblyjs/ieee754 — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/ieee754`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fieee754/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/ieee754/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_ieee754-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 101. @webassemblyjs/leb128 — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/leb128`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fleb128/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/leb128/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/webassemblyjs_leb128-1.13.2/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 102. @webassemblyjs/utf8 — 1.13.2

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/utf8`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Futf8/1.13.2)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/utf8/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_utf8-1.13.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 103. @webassemblyjs/wasm-edit — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/wasm-edit`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fwasm-edit/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/wasm-edit/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_wasm-edit-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 104. @webassemblyjs/wasm-gen — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/wasm-gen`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fwasm-gen/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/wasm-gen/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_wasm-gen-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 105. @webassemblyjs/wasm-opt — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/wasm-opt`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fwasm-opt/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/wasm-opt/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_wasm-opt-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 106. @webassemblyjs/wasm-parser — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/wasm-parser`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fwasm-parser/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/wasm-parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_wasm-parser-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 107. @webassemblyjs/wast-printer — 1.14.1

- 范围/位置：B；`renderer/node_modules/@webassemblyjs/wast-printer`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sven Sauleau <sven@sauleau.com>。
- 来源：[对应来源](https://registry.npmjs.org/@webassemblyjs%2Fwast-printer/1.14.1)；[对应来源](https://github.com/xtuc/webassemblyjs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@webassemblyjs/wast-printer/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webassemblyjs_wast-printer-1.14.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 108. @xtuc/ieee754 — 1.2.0

- 范围/位置：B；`renderer/node_modules/@xtuc/ieee754`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2008, Fair Oaks Labs, Inc.。
- 来源：[对应来源](https://registry.npmjs.org/@xtuc%2Fieee754/1.2.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@xtuc/ieee754/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/xtuc_ieee754-1.2.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 109. @xtuc/long — 4.2.2

- 范围/位置：B；`renderer/node_modules/@xtuc/long`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/@xtuc%2Flong/4.2.2)；[对应来源](https://github.com/dcodeIO/long.js.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/@xtuc/long/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/xtuc_long-4.2.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 110. acorn — 8.18.0

- 范围/位置：B；`renderer/node_modules/acorn`。
- 许可：MIT。组件版权声明：Copyright (C) 2012-2022 by various contributors (see AUTHORS)。
- 来源：[对应来源](https://registry.npmjs.org/acorn/8.18.0)；[对应来源](https://github.com/acornjs/acorn.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/acorn/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/acorn-8.18.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 111. acorn-import-phases — 1.0.4

- 范围/位置：B；`renderer/node_modules/acorn-import-phases`。
- 许可：MIT。组件版权声明：Copyright (c) 2025 Nicolò Ribaudo。
- 来源：[对应来源](https://registry.npmjs.org/acorn-import-phases/1.0.4)；[对应来源](https://github.com/nicolo-ribaudo/acorn-import-phases.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/acorn-import-phases/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/acorn-import-phases-1.0.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 112. ajv — 8.20.0

- 范围/位置：B；`renderer/node_modules/ajv`。
- 许可：MIT。组件版权声明：Copyright (c) 2015-2021 Evgeny Poberezkin。
- 来源：[对应来源](https://registry.npmjs.org/ajv/8.20.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ajv/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/ajv-8.20.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 113. ajv-formats — 2.1.1

- 范围/位置：B；`renderer/node_modules/ajv-formats`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Evgeny Poberezkin。
- 来源：[对应来源](https://registry.npmjs.org/ajv-formats/2.1.1)；[对应来源](https://github.com/ajv-validator/ajv-formats.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ajv-formats/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/ajv-formats-2.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 114. ajv-keywords — 5.1.0

- 范围/位置：B；`renderer/node_modules/ajv-keywords`。
- 许可：MIT。组件版权声明：Copyright (c) 2016 Evgeny Poberezkin。
- 来源：[对应来源](https://registry.npmjs.org/ajv-keywords/5.1.0)；[对应来源](https://github.com/epoberezkin/ajv-keywords.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ajv-keywords/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/ajv-keywords-5.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 115. argparse — 2.0.1

- 范围/位置：B；`renderer/node_modules/argparse`。
- 许可：Python-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/argparse/2.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/argparse/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/argparse-2.0.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 116. ast-types — 0.16.1

- 范围/位置：B；`renderer/node_modules/ast-types`。
- 许可：MIT。组件版权声明：Copyright (c) 2013 Ben Newman <bn@cs.stanford.edu>。
- 来源：[对应来源](https://registry.npmjs.org/ast-types/0.16.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ast-types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/ast-types-0.16.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 117. baseline-browser-mapping — 2.11.15

- 范围/位置：B；`renderer/node_modules/baseline-browser-mapping`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/baseline-browser-mapping/2.11.15)；[对应来源](https://github.com/web-platform-dx/baseline-browser-mapping.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/baseline-browser-mapping/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/baseline-browser-mapping-2.11.15/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 118. browserslist — 4.28.8

- 范围/位置：B；`renderer/node_modules/browserslist`。
- 许可：MIT。组件版权声明：Copyright 2014 Andrey Sitnik <andrey@sitnik.es> and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/browserslist/4.28.8)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/browserslist/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/browserslist-4.28.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 119. buffer-from — 1.1.2

- 范围/位置：B；`renderer/node_modules/buffer-from`。
- 许可：MIT。组件版权声明：Copyright (c) 2016, 2018 Linus Unnebäck。
- 来源：[对应来源](https://registry.npmjs.org/buffer-from/1.1.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/buffer-from/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/buffer-from-1.1.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 120. callsites — 3.1.0

- 范围/位置：B；`renderer/node_modules/callsites`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/callsites/3.1.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/callsites/package.json`。
- 完整原文及现有材料：[license](materials/npm/callsites-3.1.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 121. camelcase — 6.3.0

- 范围/位置：B；`renderer/node_modules/camelcase`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/camelcase/6.3.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/camelcase/package.json`。
- 完整原文及现有材料：[license](materials/npm/camelcase-6.3.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 122. caniuse-lite — 1.0.30001809

- 范围/位置：B；`renderer/node_modules/caniuse-lite`。
- 许可：CC-BY-4.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/caniuse-lite/1.0.30001809)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/caniuse-lite/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/caniuse-lite-1.0.30001809/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 123. chrome-trace-event — 1.0.4

- 范围/位置：B；`renderer/node_modules/chrome-trace-event`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 Joyent Inc. All rights reserved.。
- 来源：[对应来源](https://registry.npmjs.org/chrome-trace-event/1.0.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/chrome-trace-event/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/chrome-trace-event-1.0.4/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 124. commander — 2.20.3

- 范围/位置：B；`renderer/node_modules/commander`。
- 许可：MIT。组件版权声明：Copyright (c) 2011 TJ Holowaychuk <tj@vision-media.ca>。
- 来源：[对应来源](https://registry.npmjs.org/commander/2.20.3)；[对应来源](https://github.com/tj/commander.js.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/commander/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/commander-2.20.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 125. convert-source-map — 2.0.0

- 范围/位置：B；`renderer/node_modules/convert-source-map`。
- 许可：MIT。组件版权声明：Copyright 2013 Thorsten Lorenz.。
- 来源：[对应来源](https://registry.npmjs.org/convert-source-map/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/convert-source-map/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/convert-source-map-2.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 126. cosmiconfig — 8.3.6

- 范围/位置：B；`renderer/node_modules/cosmiconfig`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 David Clark。
- 来源：[对应来源](https://registry.npmjs.org/cosmiconfig/8.3.6)；[对应来源](https://github.com/cosmiconfig/cosmiconfig.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/cosmiconfig/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/cosmiconfig-8.3.6/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 127. cross-spawn — 7.0.6

- 范围/位置：B；`renderer/node_modules/cross-spawn`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Made With MOXY Lda <hello@moxy.studio>。
- 来源：[对应来源](https://registry.npmjs.org/cross-spawn/7.0.6)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/cross-spawn/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/cross-spawn-7.0.6/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 128. css-loader — 7.1.4

- 范围/位置：B；`renderer/node_modules/css-loader`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/css-loader/7.1.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/css-loader/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/css-loader-7.1.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 129. semver — 7.8.5

- 范围/位置：B；`renderer/node_modules/css-loader/node_modules/semver`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/semver/7.8.5)；[对应来源](https://github.com/npm/node-semver.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/css-loader/node_modules/semver/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/semver-7.8.5/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 130. cssesc — 3.0.0

- 范围/位置：B；`renderer/node_modules/cssesc`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/cssesc/3.0.0)；[对应来源](https://github.com/mathiasbynens/cssesc.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/cssesc/package.json`。
- 完整原文及现有材料：[LICENSE-MIT.txt](materials/npm/cssesc-3.0.0/LICENSE-MIT.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 131. csstype — 3.2.3

- 范围/位置：B；`renderer/node_modules/csstype`。
- 许可：MIT。组件版权声明：Copyright (c) 2017-2018 Fredrik Nicol。
- 来源：[对应来源](https://registry.npmjs.org/csstype/3.2.3)；[对应来源](https://github.com/frenic/csstype)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/csstype/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/csstype-3.2.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 132. debug — 4.4.3

- 范围/位置：B；`renderer/node_modules/debug`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-2017 TJ Holowaychuk <tj@vision-media.ca>；Copyright (c) 2018-2021 Josh Junon。
- 来源：[对应来源](https://registry.npmjs.org/debug/4.4.3)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/debug/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/debug-4.4.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 133. define-lazy-prop — 2.0.0

- 范围/位置：B；`renderer/node_modules/define-lazy-prop`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/define-lazy-prop/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/define-lazy-prop/package.json`。
- 完整原文及现有材料：[license](materials/npm/define-lazy-prop-2.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 134. dot-case — 3.0.4

- 范围/位置：B；`renderer/node_modules/dot-case`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Blake Embrey (hello@blakeembrey.com)。
- 来源：[对应来源](https://registry.npmjs.org/dot-case/3.0.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/dot-case/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/dot-case-3.0.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 135. dotenv — 17.3.1

- 范围/位置：B；`renderer/node_modules/dotenv`。
- 许可：BSD-2-Clause。组件版权声明：Copyright (c) 2015, Scott Motte。
- 来源：[对应来源](https://registry.npmjs.org/dotenv/17.3.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/dotenv/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/dotenv-17.3.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 136. electron-to-chromium — 1.5.411

- 范围/位置：B；`renderer/node_modules/electron-to-chromium`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/electron-to-chromium/1.5.411)；[对应来源](https://github.com/Kilian/electron-to-chromium.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/electron-to-chromium/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/electron-to-chromium-1.5.411/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 137. enhanced-resolve — 5.24.5

- 范围/位置：B；`renderer/node_modules/enhanced-resolve`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/enhanced-resolve/5.24.5)；[对应来源](https://github.com/webpack/enhanced-resolve.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/enhanced-resolve/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/enhanced-resolve-5.24.5/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 138. entities — 4.5.0

- 范围/位置：B；`renderer/node_modules/entities`。
- 许可：BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/entities/4.5.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/entities/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/entities-4.5.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 139. error-ex — 1.3.4

- 范围/位置：B；`renderer/node_modules/error-ex`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 JD Ballard。
- 来源：[对应来源](https://registry.npmjs.org/error-ex/1.3.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/error-ex/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/error-ex-1.3.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 140. error-stack-parser — 2.1.4

- 范围/位置：B；`renderer/node_modules/error-stack-parser`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Eric Wendelin and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/error-stack-parser/2.1.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/error-stack-parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/error-stack-parser-2.1.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 141. es-module-lexer — 2.3.2

- 范围/位置：B；`renderer/node_modules/es-module-lexer`。
- 许可：MIT。组件版权声明：Copyright (C) 2018-2022 Guy Bedford。
- 来源：[对应来源](https://registry.npmjs.org/es-module-lexer/2.3.2)；[对应来源](https://github.com/guybedford/es-module-lexer.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/es-module-lexer/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/es-module-lexer-2.3.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 142. esbuild — 0.28.1

- 范围/位置：B；`renderer/node_modules/esbuild`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Evan Wallace。
- 来源：[对应来源](https://registry.npmjs.org/esbuild/0.28.1)；[对应来源](https://github.com/evanw/esbuild.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/esbuild/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/esbuild-0.28.1/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 143. escalade — 3.2.0

- 范围/位置：B；`renderer/node_modules/escalade`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/escalade/3.2.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/escalade/package.json`。
- 完整原文及现有材料：[license](materials/npm/escalade-3.2.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 144. eslint-scope — 5.1.1

- 范围/位置：B；`renderer/node_modules/eslint-scope`。
- 许可：BSD-2-Clause。组件版权声明：Copyright (C) 2012-2013 Yusuke Suzuki (twitter: @Constellation) and other contributors.。
- 来源：[对应来源](https://registry.npmjs.org/eslint-scope/5.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/eslint-scope/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/eslint-scope-5.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 145. esprima — 4.0.1

- 范围/位置：B；`renderer/node_modules/esprima`。
- 许可：BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/esprima/4.0.1)；[对应来源](https://github.com/jquery/esprima.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/esprima/package.json`。
- 完整原文及现有材料：[LICENSE.BSD](materials/npm/esprima-4.0.1/LICENSE.BSD)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 146. esrecurse — 4.3.0

- 范围/位置：B；`renderer/node_modules/esrecurse`。
- 许可：BSD-2-Clause。组件版权声明：Copyright (C) 2014 Yusuke Suzuki <utatane.tea@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/esrecurse/4.3.0)；[对应来源](https://github.com/estools/esrecurse.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/esrecurse/package.json`。
- 完整原文及现有材料：[LICENSE-from-source-header.txt](materials/npm/esrecurse-4.3.0/LICENSE-from-source-header.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 147. estraverse — 5.3.0

- 范围/位置：B；`renderer/node_modules/esrecurse/node_modules/estraverse`。
- 许可：BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/estraverse/5.3.0)；[对应来源](http://github.com/estools/estraverse.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/esrecurse/node_modules/estraverse/package.json`。
- 完整原文及现有材料：[LICENSE.BSD](materials/npm/estraverse-5.3.0/LICENSE.BSD)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 148. estraverse — 4.3.0

- 范围/位置：B；`renderer/node_modules/estraverse`。
- 许可：BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/estraverse/4.3.0)；[对应来源](http://github.com/estools/estraverse.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/estraverse/package.json`。
- 完整原文及现有材料：[LICENSE.BSD](materials/npm/estraverse-4.3.0/LICENSE.BSD)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 149. events — 3.3.0

- 范围/位置：B；`renderer/node_modules/events`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/events/3.3.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/events/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/events-3.3.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 150. execa — 5.1.1

- 范围/位置：B；`renderer/node_modules/execa`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/execa/5.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/execa/package.json`。
- 完整原文及现有材料：[license](materials/npm/execa-5.1.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 151. fast-deep-equal — 3.1.3

- 范围/位置：B；`renderer/node_modules/fast-deep-equal`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Evgeny Poberezkin。
- 来源：[对应来源](https://registry.npmjs.org/fast-deep-equal/3.1.3)；[对应来源](https://github.com/epoberezkin/fast-deep-equal.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/fast-deep-equal/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/fast-deep-equal-3.1.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 152. fast-uri — 3.1.5

- 范围/位置：B；`renderer/node_modules/fast-uri`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2011-2021, Gary Court until https://github.com/garycourt/uri-js/commit/a1acf730b4bba3f1097c9f52e7d9d3aba8cdcaae；Copyright (c) 2021-present The Fastify team <https://github.com/fastify/fastify#team>。
- 来源：[对应来源](https://registry.npmjs.org/fast-uri/3.1.5)；[对应来源](https://github.com/fastify/fast-uri.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/fast-uri/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/fast-uri-3.1.5/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 153. fast-uri/benchmark (internal package manifest) — internal 1.0.0; parent 3.1.5

- 范围/位置：B；`renderer/node_modules/fast-uri/benchmark`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/fast-uri/3.1.5)；[对应来源](https://github.com/fastify/fast-uri.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/fast-uri/benchmark/package.json`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E；这是包内子目录清单，不是同名npm包的版本；版本来源须查询父包。内部声明与父包不同的部分仍待逐文件核查。。

## 154. fs-monkey — 1.0.3

- 范围/位置：B；`renderer/node_modules/fs-monkey`。
- 许可：Unlicense。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/fs-monkey/1.0.3)；[对应来源](https://github.com/streamich/fs-monkey.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/fs-monkey/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/fs-monkey-1.0.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 155. gensync — 1.0.0-beta.2

- 范围/位置：B；`renderer/node_modules/gensync`。
- 许可：MIT。组件版权声明：Copyright 2018 Logan Smyth <loganfsmyth@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/gensync/1.0.0-beta.2)；[对应来源](https://github.com/loganfsmyth/gensync.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/gensync/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/gensync-1.0.0-beta.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 156. get-stream — 6.0.1

- 范围/位置：B；`renderer/node_modules/get-stream`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/get-stream/6.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/get-stream/package.json`。
- 完整原文及现有材料：[license](materials/npm/get-stream-6.0.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 157. glob-to-regexp — 0.4.1

- 范围/位置：B；`renderer/node_modules/glob-to-regexp`。
- 许可：BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/glob-to-regexp/0.4.1)；[对应来源](https://github.com/fitzgen/glob-to-regexp.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/glob-to-regexp/package.json`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 158. graceful-fs — 4.2.11

- 范围/位置：B；`renderer/node_modules/graceful-fs`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/graceful-fs/4.2.11)；[对应来源](https://github.com/isaacs/node-graceful-fs)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/graceful-fs/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/graceful-fs-4.2.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 159. gsap — 3.15.0

- 范围/位置：A,B；`renderer/node_modules/gsap`。
- 许可：Standard 'no charge' license: https://gsap.com/standard-license.。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/gsap/3.15.0)；[对应来源](https://gsap.com/standard-license/)；[对应来源](https://raw.githubusercontent.com/greensock/GSAP/3.15.0/README.md)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/gsap/package.json`。
- 完整原文及现有材料：[standard-license.original.html.txt](materials/gsap/3.15.0/standard-license.original.html.txt)；[standard-license.txt](materials/gsap/3.15.0/standard-license.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：保留3.15.0版权头并补许可快照；核对Studio实际编辑能力与Prohibited Uses；网页仅展示和产品运行时分别判断。

## 160. has-flag — 4.0.0

- 范围/位置：B；`renderer/node_modules/has-flag`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/has-flag/4.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/has-flag/package.json`。
- 完整原文及现有材料：[license](materials/npm/has-flag-4.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 161. html-entities — 2.6.0

- 范围/位置：B；`renderer/node_modules/html-entities`。
- 许可：MIT。组件版权声明：Copyright (c) 2021 Dulin Marat。
- 来源：[对应来源](https://registry.npmjs.org/html-entities/2.6.0)；[对应来源](https://github.com/mdevils/html-entities.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/html-entities/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/html-entities-2.6.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 162. human-signals — 2.1.0

- 范围/位置：B；`renderer/node_modules/human-signals`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/human-signals/2.1.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/human-signals/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/human-signals-2.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 163. icss-utils — 5.1.0

- 范围/位置：B；`renderer/node_modules/icss-utils`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/icss-utils/5.1.0)；[对应来源](https://github.com/css-modules/icss-utils.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/icss-utils/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/icss-utils-5.1.0/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 164. import-fresh — 3.3.1

- 范围/位置：B；`renderer/node_modules/import-fresh`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/import-fresh/3.3.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/import-fresh/package.json`。
- 完整原文及现有材料：[license](materials/npm/import-fresh-3.3.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 165. is-arrayish — 0.2.1

- 范围/位置：B；`renderer/node_modules/is-arrayish`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 JD Ballard。
- 来源：[对应来源](https://registry.npmjs.org/is-arrayish/0.2.1)；[对应来源](https://github.com/qix-/node-is-arrayish.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/is-arrayish/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/is-arrayish-0.2.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 166. is-docker — 2.2.1

- 范围/位置：B；`renderer/node_modules/is-docker`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/is-docker/2.2.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/is-docker/package.json`。
- 完整原文及现有材料：[license](materials/npm/is-docker-2.2.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 167. is-stream — 2.0.1

- 范围/位置：B；`renderer/node_modules/is-stream`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/is-stream/2.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/is-stream/package.json`。
- 完整原文及现有材料：[license](materials/npm/is-stream-2.0.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 168. is-wsl — 2.2.0

- 范围/位置：B；`renderer/node_modules/is-wsl`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/is-wsl/2.2.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/is-wsl/package.json`。
- 完整原文及现有材料：[license](materials/npm/is-wsl-2.2.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 169. isexe — 2.0.0

- 范围/位置：B；`renderer/node_modules/isexe`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/isexe/2.0.0)；[对应来源](https://github.com/isaacs/isexe.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/isexe/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/isexe-2.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 170. jest-worker — 27.5.1

- 范围/位置：B；`renderer/node_modules/jest-worker`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/jest-worker/27.5.1)；[对应来源](https://github.com/facebook/jest.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/jest-worker/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/jest-worker-27.5.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 171. js-tokens — 4.0.0

- 范围/位置：B；`renderer/node_modules/js-tokens`。
- 许可：MIT。组件版权声明：Copyright (c) 2014, 2015, 2016, 2017, 2018 Simon Lydell。
- 来源：[对应来源](https://registry.npmjs.org/js-tokens/4.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/js-tokens/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/js-tokens-4.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 172. js-yaml — 4.3.1

- 范围/位置：B；`renderer/node_modules/js-yaml`。
- 许可：MIT。组件版权声明：Copyright (C) 2011-2015 by Vitaly Puzrin。
- 来源：[对应来源](https://registry.npmjs.org/js-yaml/4.3.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/js-yaml/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/js-yaml-4.3.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 173. jsesc — 3.1.0

- 范围/位置：B；`renderer/node_modules/jsesc`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/jsesc/3.1.0)；[对应来源](https://github.com/mathiasbynens/jsesc.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/jsesc/package.json`。
- 完整原文及现有材料：[LICENSE-MIT.txt](materials/npm/jsesc-3.1.0/LICENSE-MIT.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 174. json-parse-even-better-errors — 2.3.1

- 范围/位置：B；`renderer/node_modules/json-parse-even-better-errors`。
- 许可：MIT。组件版权声明：Copyright 2017 Kat Marchán。
- 来源：[对应来源](https://registry.npmjs.org/json-parse-even-better-errors/2.3.1)；[对应来源](https://github.com/npm/json-parse-even-better-errors)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/json-parse-even-better-errors/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/json-parse-even-better-errors-2.3.1/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 175. json-schema-traverse — 1.0.0

- 范围/位置：B；`renderer/node_modules/json-schema-traverse`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Evgeny Poberezkin。
- 来源：[对应来源](https://registry.npmjs.org/json-schema-traverse/1.0.0)；[对应来源](https://github.com/epoberezkin/json-schema-traverse.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/json-schema-traverse/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/json-schema-traverse-1.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 176. json5 — 2.2.3

- 范围/位置：B；`renderer/node_modules/json5`。
- 许可：MIT。组件版权声明：Copyright (c) 2012-2018 Aseem Kishore, and [others].。
- 来源：[对应来源](https://registry.npmjs.org/json5/2.2.3)；[对应来源](https://github.com/json5/json5.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/json5/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/json5-2.2.3/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 177. kiwi-schema — 0.5.0

- 范围/位置：B；`renderer/node_modules/kiwi-schema`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/kiwi-schema/0.5.0)；[对应来源](https://github.com/evanw/kiwi.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/kiwi-schema/package.json`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 178. kleur — 3.0.3

- 范围/位置：B；`renderer/node_modules/kleur`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/kleur/3.0.3)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/kleur/package.json`。
- 完整原文及现有材料：[license](materials/npm/kleur-3.0.3/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 179. lines-and-columns — 1.2.4

- 范围/位置：B；`renderer/node_modules/lines-and-columns`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 Brian Donovan。
- 来源：[对应来源](https://registry.npmjs.org/lines-and-columns/1.2.4)；[对应来源](https://github.com/eventualbuddha/lines-and-columns.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/lines-and-columns/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/lines-and-columns-1.2.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 180. loader-runner — 4.3.2

- 范围/位置：B；`renderer/node_modules/loader-runner`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/loader-runner/4.3.2)；[对应来源](https://github.com/webpack/loader-runner.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/loader-runner/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/loader-runner-4.3.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 181. lower-case — 2.0.2

- 范围/位置：B；`renderer/node_modules/lower-case`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Blake Embrey (hello@blakeembrey.com)。
- 来源：[对应来源](https://registry.npmjs.org/lower-case/2.0.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/lower-case/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/lower-case-2.0.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 182. lru-cache — 5.1.1

- 范围/位置：B；`renderer/node_modules/lru-cache`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/lru-cache/5.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/lru-cache/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/lru-cache-5.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 183. mediabunny — 1.50.8

- 范围/位置：B；`renderer/node_modules/mediabunny`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/mediabunny/1.50.8)；[对应来源](https://github.com/Vanilagy/mediabunny.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/mediabunny/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mediabunny-1.50.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 184. memfs — 3.4.3

- 范围/位置：B；`renderer/node_modules/memfs`。
- 许可：Unlicense。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/memfs/3.4.3)；[对应来源](https://github.com/streamich/memfs.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/memfs/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/memfs-3.4.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 185. merge-stream — 2.0.0

- 范围/位置：B；`renderer/node_modules/merge-stream`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/merge-stream/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/merge-stream/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/merge-stream-2.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 186. mime-db — 1.52.0

- 范围/位置：B；`renderer/node_modules/mime-db`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Jonathan Ong <me@jongleberry.com>；Copyright (c) 2015-2022 Douglas Christopher Wilson <doug@somethingdoug.com>。
- 来源：[对应来源](https://registry.npmjs.org/mime-db/1.52.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/mime-db/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mime-db-1.52.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 187. mime-types — 2.1.35

- 范围/位置：B；`renderer/node_modules/mime-types`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Jonathan Ong <me@jongleberry.com>；Copyright (c) 2015 Douglas Christopher Wilson <doug@somethingdoug.com>。
- 来源：[对应来源](https://registry.npmjs.org/mime-types/2.1.35)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/mime-types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/mime-types-2.1.35/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 188. mimic-fn — 2.1.0

- 范围/位置：B；`renderer/node_modules/mimic-fn`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/mimic-fn/2.1.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/mimic-fn/package.json`。
- 完整原文及现有材料：[license](materials/npm/mimic-fn-2.1.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 189. minimist — 1.2.6

- 范围/位置：B；`renderer/node_modules/minimist`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/minimist/1.2.6)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/minimist/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/minimist-1.2.6/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 190. ms — 2.1.3

- 范围/位置：B；`renderer/node_modules/ms`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Vercel, Inc.。
- 来源：[对应来源](https://registry.npmjs.org/ms/2.1.3)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ms/package.json`。
- 完整原文及现有材料：[license.md](materials/npm/ms-2.1.3/license.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 191. nanoid — 3.3.18

- 范围/位置：B；`renderer/node_modules/nanoid`。
- 许可：MIT。组件版权声明：Copyright 2017 Andrey Sitnik <andrey@sitnik.ru>。
- 来源：[对应来源](https://registry.npmjs.org/nanoid/3.3.18)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/nanoid/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/nanoid-3.3.18/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 192. neo-async — 2.6.2

- 范围/位置：B；`renderer/node_modules/neo-async`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-2018 Suguru Motegi。
- 来源：[对应来源](https://registry.npmjs.org/neo-async/2.6.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/neo-async/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/neo-async-2.6.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 193. no-case — 3.0.4

- 范围/位置：B；`renderer/node_modules/no-case`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Blake Embrey (hello@blakeembrey.com)。
- 来源：[对应来源](https://registry.npmjs.org/no-case/3.0.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/no-case/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/no-case-3.0.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 194. node-releases — 2.0.53

- 范围/位置：B；`renderer/node_modules/node-releases`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Sergey Rubanov (https://github.com/chicoxyzzy)。
- 来源：[对应来源](https://registry.npmjs.org/node-releases/2.0.53)；[对应来源](https://github.com/chicoxyzzy/node-releases.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/node-releases/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/node-releases-2.0.53/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 195. npm-run-path — 4.0.1

- 范围/位置：B；`renderer/node_modules/npm-run-path`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/npm-run-path/4.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/npm-run-path/package.json`。
- 完整原文及现有材料：[license](materials/npm/npm-run-path-4.0.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 196. onetime — 5.1.2

- 范围/位置：B；`renderer/node_modules/onetime`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/onetime/5.1.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/onetime/package.json`。
- 完整原文及现有材料：[license](materials/npm/onetime-5.1.2/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 197. open — 8.4.2

- 范围/位置：B；`renderer/node_modules/open`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/open/8.4.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/open/package.json`。
- 完整原文及现有材料：[license](materials/npm/open-8.4.2/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 198. parent-module — 1.0.1

- 范围/位置：B；`renderer/node_modules/parent-module`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/parent-module/1.0.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/parent-module/package.json`。
- 完整原文及现有材料：[license](materials/npm/parent-module-1.0.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 199. parse-json — 5.2.0

- 范围/位置：B；`renderer/node_modules/parse-json`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/parse-json/5.2.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/parse-json/package.json`。
- 完整原文及现有材料：[license](materials/npm/parse-json-5.2.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 200. path-key — 3.1.1

- 范围/位置：B；`renderer/node_modules/path-key`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/path-key/3.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/path-key/package.json`。
- 完整原文及现有材料：[license](materials/npm/path-key-3.1.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 201. path-type — 4.0.0

- 范围/位置：B；`renderer/node_modules/path-type`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/path-type/4.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/path-type/package.json`。
- 完整原文及现有材料：[license](materials/npm/path-type-4.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 202. picocolors — 1.1.1

- 范围/位置：B；`renderer/node_modules/picocolors`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/picocolors/1.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/picocolors/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/picocolors-1.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 203. postcss — 8.5.26

- 范围/位置：B；`renderer/node_modules/postcss`。
- 许可：MIT。组件版权声明：Copyright 2013 Andrey Sitnik <andrey@sitnik.es>。
- 来源：[对应来源](https://registry.npmjs.org/postcss/8.5.26)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-8.5.26/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 204. postcss-modules-extract-imports — 3.1.0

- 范围/位置：B；`renderer/node_modules/postcss-modules-extract-imports`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/postcss-modules-extract-imports/3.1.0)；[对应来源](https://github.com/css-modules/postcss-modules-extract-imports.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-modules-extract-imports/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-modules-extract-imports-3.1.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 205. postcss-modules-local-by-default — 4.2.0

- 范围/位置：B；`renderer/node_modules/postcss-modules-local-by-default`。
- 许可：MIT。组件版权声明：Copyright 2015 Mark Dalgleish <mark.john.dalgleish@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/postcss-modules-local-by-default/4.2.0)；[对应来源](https://github.com/css-modules/postcss-modules-local-by-default.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-modules-local-by-default/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-modules-local-by-default-4.2.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 206. postcss-modules-scope — 3.2.1

- 范围/位置：B；`renderer/node_modules/postcss-modules-scope`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/postcss-modules-scope/3.2.1)；[对应来源](https://github.com/css-modules/postcss-modules-scope.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-modules-scope/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-modules-scope-3.2.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 207. postcss-modules-values — 4.0.0

- 范围/位置：B；`renderer/node_modules/postcss-modules-values`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/postcss-modules-values/4.0.0)；[对应来源](https://github.com/css-modules/postcss-modules-values.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-modules-values/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-modules-values-4.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 208. postcss-selector-parser — 7.1.5

- 范围/位置：B；`renderer/node_modules/postcss-selector-parser`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/postcss-selector-parser/7.1.5)；[对应来源](https://github.com/postcss/postcss-selector-parser.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-selector-parser/package.json`。
- 完整原文及现有材料：[LICENSE-MIT](materials/npm/postcss-selector-parser-7.1.5/LICENSE-MIT)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 209. postcss-value-parser — 4.2.0

- 范围/位置：B；`renderer/node_modules/postcss-value-parser`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/postcss-value-parser/4.2.0)；[对应来源](https://github.com/TrySound/postcss-value-parser.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/postcss-value-parser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/postcss-value-parser-4.2.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 210. prettier — 3.8.1

- 范围/位置：B；`renderer/node_modules/prettier`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/prettier/3.8.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/prettier/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/prettier-3.8.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 211. prompts — 2.4.2

- 范围/位置：B；`renderer/node_modules/prompts`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Terkel Gjervig Nielsen。
- 来源：[对应来源](https://registry.npmjs.org/prompts/2.4.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/prompts/package.json`。
- 完整原文及现有材料：[license](materials/npm/prompts-2.4.2/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 212. react — 19.2.8

- 范围/位置：B；`renderer/node_modules/react`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/react/19.2.8)；[对应来源](https://github.com/react/react.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/react/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/react-19.2.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 213. react-dom — 19.2.8

- 范围/位置：B；`renderer/node_modules/react-dom`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/react-dom/19.2.8)；[对应来源](https://github.com/react/react.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/react-dom/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/react-dom-19.2.8/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 214. react-refresh — 0.18.0

- 范围/位置：B；`renderer/node_modules/react-refresh`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/react-refresh/0.18.0)；[对应来源](https://github.com/facebook/react.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/react-refresh/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/react-refresh-0.18.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 215. recast — 0.23.11

- 范围/位置：B；`renderer/node_modules/recast`。
- 许可：MIT。组件版权声明：Copyright (c) 2012 Ben Newman <bn@cs.stanford.edu>。
- 来源：[对应来源](https://registry.npmjs.org/recast/0.23.11)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/recast/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/recast-0.23.11/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 216. source-map — 0.6.1

- 范围/位置：B；`renderer/node_modules/recast/node_modules/source-map`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009-2011, Mozilla Foundation and contributors。
- 来源：[对应来源](https://registry.npmjs.org/source-map/0.6.1)；[对应来源](http://github.com/mozilla/source-map.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/recast/node_modules/source-map/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/source-map-0.6.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 217. remotion — 4.0.513

- 范围/位置：B；`renderer/node_modules/remotion`。
- 许可：SEE LICENSE IN LICENSE.md。组件版权声明：Copyright © 2026 [Remotion](https://www.remotion.dev)。
- 来源：[对应来源](https://registry.npmjs.org/remotion/4.0.513)；[对应来源](https://raw.githubusercontent.com/remotion-dev/remotion/v4.0.513/LICENSE.md)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/remotion/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/remotion-4.0.513/LICENSE.md)；[LICENSE.md](materials/remotion/4.0.513/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：取得覆盖桌面应用嵌入再分发和下游资格的明确许可结论/授权；不是仅导出视频。

## 218. require-from-string — 2.0.2

- 范围/位置：B；`renderer/node_modules/require-from-string`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/require-from-string/2.0.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/require-from-string/package.json`。
- 完整原文及现有材料：[license](materials/npm/require-from-string-2.0.2/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 219. resolve-from — 4.0.0

- 范围/位置：B；`renderer/node_modules/resolve-from`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/resolve-from/4.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/resolve-from/package.json`。
- 完整原文及现有材料：[license](materials/npm/resolve-from-4.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 220. scheduler — 0.27.0

- 范围/位置：B；`renderer/node_modules/scheduler`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/scheduler/0.27.0)；[对应来源](https://github.com/facebook/react.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/scheduler/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/scheduler-0.27.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 221. schema-utils — 4.3.3

- 范围/位置：B；`renderer/node_modules/schema-utils`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/schema-utils/4.3.3)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/schema-utils/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/schema-utils-4.3.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 222. semver — 7.5.3

- 范围/位置：B；`renderer/node_modules/semver`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/semver/7.5.3)；[对应来源](https://github.com/npm/node-semver.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/semver/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/semver-7.5.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 223. lru-cache — 6.0.0

- 范围/位置：B；`renderer/node_modules/semver/node_modules/lru-cache`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/lru-cache/6.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/semver/node_modules/lru-cache/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/lru-cache-6.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 224. yallist — 4.0.0

- 范围/位置：B；`renderer/node_modules/semver/node_modules/yallist`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/yallist/4.0.0)；[对应来源](https://github.com/isaacs/yallist.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/semver/node_modules/yallist/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/yallist-4.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 225. shebang-command — 2.0.0

- 范围/位置：B；`renderer/node_modules/shebang-command`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/shebang-command/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/shebang-command/package.json`。
- 完整原文及现有材料：[license](materials/npm/shebang-command-2.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 226. shebang-regex — 3.0.0

- 范围/位置：B；`renderer/node_modules/shebang-regex`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/shebang-regex/3.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/shebang-regex/package.json`。
- 完整原文及现有材料：[license](materials/npm/shebang-regex-3.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 227. signal-exit — 3.0.7

- 范围/位置：B；`renderer/node_modules/signal-exit`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/signal-exit/3.0.7)；[对应来源](https://github.com/tapjs/signal-exit.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/signal-exit/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/signal-exit-3.0.7/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 228. sisteransi — 1.0.5

- 范围/位置：B；`renderer/node_modules/sisteransi`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Terkel Gjervig Nielsen。
- 来源：[对应来源](https://registry.npmjs.org/sisteransi/1.0.5)；[对应来源](https://github.com/terkelg/sisteransi)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/sisteransi/package.json`。
- 完整原文及现有材料：[license](materials/npm/sisteransi-1.0.5/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 229. snake-case — 3.0.4

- 范围/位置：B；`renderer/node_modules/snake-case`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Blake Embrey (hello@blakeembrey.com)。
- 来源：[对应来源](https://registry.npmjs.org/snake-case/3.0.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/snake-case/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/snake-case-3.0.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 230. source-map — 0.8.0

- 范围/位置：B；`renderer/node_modules/source-map`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009-2011, Mozilla Foundation and contributors。
- 来源：[对应来源](https://registry.npmjs.org/source-map/0.8.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/source-map/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/source-map-0.8.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 231. source-map-js — 1.2.1

- 范围/位置：B；`renderer/node_modules/source-map-js`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009-2011, Mozilla Foundation and contributors。
- 来源：[对应来源](https://registry.npmjs.org/source-map-js/1.2.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/source-map-js/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/source-map-js-1.2.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 232. source-map-support — 0.5.21

- 范围/位置：B；`renderer/node_modules/source-map-support`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Evan Wallace。
- 来源：[对应来源](https://registry.npmjs.org/source-map-support/0.5.21)；[对应来源](https://github.com/evanw/node-source-map-support)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/source-map-support/package.json`。
- 完整原文及现有材料：[LICENSE.md](materials/npm/source-map-support-0.5.21/LICENSE.md)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 233. source-map — 0.6.1

- 范围/位置：B；`renderer/node_modules/source-map-support/node_modules/source-map`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009-2011, Mozilla Foundation and contributors。
- 来源：[对应来源](https://registry.npmjs.org/source-map/0.6.1)；[对应来源](http://github.com/mozilla/source-map.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/source-map-support/node_modules/source-map/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/source-map-0.6.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 234. stackframe — 1.3.4

- 范围/位置：B；`renderer/node_modules/stackframe`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 Eric Wendelin and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/stackframe/1.3.4)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/stackframe/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/stackframe-1.3.4/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 235. strip-final-newline — 2.0.0

- 范围/位置：B；`renderer/node_modules/strip-final-newline`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/strip-final-newline/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/strip-final-newline/package.json`。
- 完整原文及现有材料：[license](materials/npm/strip-final-newline-2.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 236. style-loader — 4.0.0

- 范围/位置：B；`renderer/node_modules/style-loader`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/style-loader/4.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/style-loader/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/style-loader-4.0.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 237. supports-color — 8.1.1

- 范围/位置：B；`renderer/node_modules/supports-color`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/supports-color/8.1.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/supports-color/package.json`。
- 完整原文及现有材料：[license](materials/npm/supports-color-8.1.1/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 238. svg-parser — 2.0.5

- 范围/位置：B；`renderer/node_modules/svg-parser`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/svg-parser/2.0.5)；[对应来源](https://github.com/Rich-Harris/svg-parser.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/svg-parser/package.json`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 239. tapable — 2.3.3

- 范围/位置：B；`renderer/node_modules/tapable`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/tapable/2.3.3)；[对应来源](http://github.com/webpack/tapable.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/tapable/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/tapable-2.3.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 240. terser — 5.50.0

- 范围/位置：B；`renderer/node_modules/terser`。
- 许可：BSD-2-Clause。组件版权声明：Copyright 2012-2018 (c) Mihai Bazon <mihai.bazon@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/terser/5.50.0)；[对应来源](https://github.com/terser/terser)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/terser/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/terser-5.50.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 241. terser/bin (internal package manifest) — internal 1.0.0; parent 5.50.0

- 范围/位置：B；`renderer/node_modules/terser/bin`。
- 许可：BSD-2-Clause。组件版权声明：Copyright 2012-2018 (c) Mihai Bazon <mihai.bazon@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/terser/5.50.0)；[对应来源](https://github.com/terser/terser)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/terser/bin/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/terser-5.50.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E；这是包内子目录清单，不是同名npm包的版本；版本来源须查询父包。内部声明与父包不同的部分仍待逐文件核查。。

## 242. terser/dist (internal package manifest) — internal 1.0.0; parent 5.50.0

- 范围/位置：B；`renderer/node_modules/terser/dist`。
- 许可：BSD-2-Clause。组件版权声明：Copyright 2012-2018 (c) Mihai Bazon <mihai.bazon@gmail.com>。
- 来源：[对应来源](https://registry.npmjs.org/terser/5.50.0)；[对应来源](https://github.com/terser/terser)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/terser/dist/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/terser-5.50.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E；这是包内子目录清单，不是同名npm包的版本；版本来源须查询父包。内部声明与父包不同的部分仍待逐文件核查。。

## 243. terser-webpack-plugin — 5.6.1

- 范围/位置：B；`renderer/node_modules/terser-webpack-plugin`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/terser-webpack-plugin/5.6.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/terser-webpack-plugin/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/terser-webpack-plugin-5.6.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 244. tiny-invariant — 1.3.3

- 范围/位置：B；`renderer/node_modules/tiny-invariant`。
- 许可：MIT。组件版权声明：Copyright (c) 2019 Alexander Reardon。
- 来源：[对应来源](https://registry.npmjs.org/tiny-invariant/1.3.3)；[对应来源](https://github.com/alexreardon/tiny-invariant.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/tiny-invariant/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/tiny-invariant-1.3.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 245. to-fast-properties — 2.0.0

- 范围/位置：B；`renderer/node_modules/to-fast-properties`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Petka Antonov。
- 来源：[对应来源](https://registry.npmjs.org/to-fast-properties/2.0.0)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/to-fast-properties/package.json`。
- 完整原文及现有材料：[license](materials/npm/to-fast-properties-2.0.0/license)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 246. tslib — 2.8.1

- 范围/位置：B；`renderer/node_modules/tslib`。
- 许可：0BSD。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/tslib/2.8.1)；[对应来源](https://github.com/Microsoft/tslib.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/tslib/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/tslib-2.8.1/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 247. typescript — 5.9.3

- 范围/位置：B；`renderer/node_modules/typescript`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/typescript/5.9.3)；[对应来源](https://github.com/microsoft/TypeScript.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/typescript/package.json`。
- 完整原文及现有材料：[LICENSE.txt](materials/npm/typescript-5.9.3/LICENSE.txt)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 248. undici-types — 8.3.0

- 范围/位置：B；`renderer/node_modules/undici-types`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/undici-types/8.3.0)；[对应来源](https://github.com/nodejs/undici.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/undici-types/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/undici-types-8.3.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 249. update-browserslist-db — 1.3.1

- 范围/位置：B；`renderer/node_modules/update-browserslist-db`。
- 许可：MIT。组件版权声明：Copyright 2022 Andrey Sitnik <andrey@sitnik.es> and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/update-browserslist-db/1.3.1)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/update-browserslist-db/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/update-browserslist-db-1.3.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 250. util-deprecate — 1.0.2

- 范围/位置：B；`renderer/node_modules/util-deprecate`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Nathan Rajlich <nathan@tootallnate.net>。
- 来源：[对应来源](https://registry.npmjs.org/util-deprecate/1.0.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/util-deprecate/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/util-deprecate-1.0.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 251. watchpack — 2.5.2

- 范围/位置：B；`renderer/node_modules/watchpack`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/watchpack/2.5.2)；[对应来源](https://github.com/webpack/watchpack.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/watchpack/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/watchpack-2.5.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 252. webpack — 5.105.0

- 范围/位置：B；`renderer/node_modules/webpack`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/webpack/5.105.0)；[对应来源](https://github.com/webpack/webpack.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/webpack/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webpack-5.105.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 253. webpack-sources — 3.5.1

- 范围/位置：B；`renderer/node_modules/webpack-sources`。
- 许可：MIT。组件版权声明：Copyright (c) 2017 JS Foundation and other contributors。
- 来源：[对应来源](https://registry.npmjs.org/webpack-sources/3.5.1)；[对应来源](https://github.com/webpack/webpack-sources.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/webpack-sources/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/webpack-sources-3.5.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 254. which — 2.0.2

- 范围/位置：B；`renderer/node_modules/which`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/which/2.0.2)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/which/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/which-2.0.2/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 255. ws — 8.21.0

- 范围/位置：B；`renderer/node_modules/ws`。
- 许可：MIT。组件版权声明：Copyright (c) 2011 Einar Otto Stangvik <einaros@gmail.com>；Copyright (c) 2013 Arnout Kazemier and contributors；Copyright (c) 2016 Luigi Pinca and contributors。
- 来源：[对应来源](https://registry.npmjs.org/ws/8.21.0)；[对应来源](https://github.com/websockets/ws.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/ws/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/ws-8.21.0/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 256. yallist — 3.1.1

- 范围/位置：B；`renderer/node_modules/yallist`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://registry.npmjs.org/yallist/3.1.1)；[对应来源](https://github.com/isaacs/yallist.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/yallist/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/yallist-3.1.1/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 257. zod — 4.4.3

- 范围/位置：B；`renderer/node_modules/zod`。
- 许可：MIT。组件版权声明：Copyright (c) 2025 Colin McDonnell。
- 来源：[对应来源](https://registry.npmjs.org/zod/4.4.3)；[对应来源](https://github.com/colinhacks/zod.git)。版本依据及SHA见机器索引对应`npm:renderer/node_modules/zod/package.json`。
- 完整原文及现有材料：[LICENSE](materials/npm/zod-4.4.3/LICENSE)
- 用途/集成：Node.js require/import，原源码/工具链随安装包复制；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：版本/实际目录已核实；元数据许可证仅为线索，未逐一核验全部上游对应版本正文；不得因devDependency标记而归E。

## 258. accelerate — 1.12.0

- 范围/位置：B；`wheels/accelerate-1.12.0-py3-none-any.whl`。
- 许可：Apache。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/accelerate/1.12.0/)；[对应来源](https://github.com/huggingface/accelerate)。版本依据及SHA见机器索引对应`wheel:wheels/accelerate-1.12.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/accelerate-1.12.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 259. annotated-doc — 0.0.5

- 范围/位置：B；`wheels/annotated_doc-0.0.5-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2025 Sebastián Ramírez。
- 来源：[对应来源](https://pypi.org/project/annotated-doc/0.0.5/)；[对应来源](https://github.com/fastapi/annotated-doc)；[对应来源](https://github.com/fastapi/annotated-doc/issues)；[对应来源](https://github.com/fastapi/annotated-doc/release-notes.md)。版本依据及SHA见机器索引对应`wheel:wheels/annotated_doc-0.0.5-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/annotated-doc-0.0.5/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 260. annotated-types — 0.8.0

- 范围/位置：B；`wheels/annotated_types-0.8.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2022 the contributors。
- 来源：[对应来源](https://pypi.org/project/annotated-types/0.8.0/)；[对应来源](https://github.com/annotated-types/annotated-types)；[对应来源](https://github.com/annotated-types/annotated-types/releases)。版本依据及SHA见机器索引对应`wheel:wheels/annotated_types-0.8.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/annotated-types-0.8.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 261. audioread — 3.1.0

- 范围/位置：B；`wheels/audioread-3.1.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2011-2018 Adrian Sampson。
- 来源：[对应来源](https://pypi.org/project/audioread/3.1.0/)；[对应来源](https://github.com/beetbox/audioread/issues)；[对应来源](https://github.com/beetbox/audioread)。版本依据及SHA见机器索引对应`wheel:wheels/audioread-3.1.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/audioread-3.1.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 262. av — 17.1.0

- 范围/位置：B；`wheels/av-17.1.0-cp310-cp310-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/av/17.1.0/)；[对应来源](https://github.com/PyAV-Org/PyAV/issues)；[对应来源](https://github.com/PyAV-Org/PyAV)；[对应来源](https://pyav.basswood-io.com)。版本依据及SHA见机器索引对应`wheel:wheels/av-17.1.0-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/av-17.1.0/LICENSE.txt)；[pyav-source.tar.gz](source-materials/pyav-17.1.0/pyav-source.tar.gz)；[pyav-ffmpeg-build-source.tar.gz](source-materials/pyav-17.1.0/pyav-ffmpeg-build-source.tar.gz)；[ffmpeg-source.tar.xz](source-materials/pyav-17.1.0/ffmpeg-source.tar.xz)；[COPYING.LGPLv2.1](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv2.1)；[COPYING.GPLv2](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv2)；[COPYING.LGPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv3)；[COPYING.GPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv3)；[x264-source.tar.bz2](source-materials/pyav-17.1.0/x264-source.tar.bz2)；[COPYING](materials/pyav-codecs/x264-source/COPYING)；[x265-source.tar.gz](source-materials/pyav-17.1.0/x265-source.tar.gz)；[COPYING](materials/pyav-codecs/x265-source/COPYING)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围；新增：pyav-ffmpeg README写x264 32c3b801，但pkg.py固定b35605ac；后者源码SHA已匹配上游脚本，DLL源码对应关系仍未闭合。x2654.2源码和原文已取得，不等于组合授权问题已解决。。

## 263. blinker — 1.9.0

- 范围/位置：B；`wheels/blinker-1.9.0-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright 2010 Jason Kirtland。
- 来源：[对应来源](https://pypi.org/project/blinker/1.9.0/)；[对应来源](https://discord.gg/pallets)；[对应来源](https://blinker.readthedocs.io)；[对应来源](https://github.com/pallets-eco/blinker/)。版本依据及SHA见机器索引对应`wheel:wheels/blinker-1.9.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/blinker-1.9.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 264. brotli — 1.2.0

- 范围/位置：B；`wheels/brotli-1.2.0-cp310-cp310-win_amd64.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.。
- 来源：[对应来源](https://pypi.org/project/brotli/1.2.0/)；[对应来源](https://github.com/google/brotli)。版本依据及SHA见机器索引对应`wheel:wheels/brotli-1.2.0-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/brotli-1.2.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 265. certifi — 2026.7.22

- 范围/位置：B；`wheels/certifi-2026.7.22-py3-none-any.whl`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/certifi/2026.7.22/)；[对应来源](https://github.com/certifi/python-certifi)。版本依据及SHA见机器索引对应`wheel:wheels/certifi-2026.7.22-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/certifi-2026.7.22/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 266. colorama — 0.4.6

- 范围/位置：B；`wheels/colorama-0.4.6-py2.py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2010 Jonathan Hartley。
- 来源：[对应来源](https://pypi.org/project/colorama/0.4.6/)；[对应来源](https://github.com/tartley/colorama)。版本依据及SHA见机器索引对应`wheel:wheels/colorama-0.4.6-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/colorama-0.4.6/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 267. decorator — 5.3.1

- 范围/位置：B；`wheels/decorator-5.3.1-py3-none-any.whl`。
- 许可：BSD-2-Clause。组件版权声明：Copyright (c) 2005-2026, Michele Simionato。
- 来源：[对应来源](https://pypi.org/project/decorator/5.3.1/)。版本依据及SHA见机器索引对应`wheel:wheels/decorator-5.3.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/decorator-5.3.1/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 268. dyNET38 — 2.2

- 范围/位置：B；`wheels/dynet38-2.2-cp310-cp310-win_amd64.whl`。
- 许可：Apache 2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/dyNET38/2.2/)；[对应来源](https://github.com/taishi-i/dynet)。版本依据及SHA见机器索引对应`wheel:wheels/dynet38-2.2-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 269. exceptiongroup — 1.3.1

- 范围/位置：B；`wheels/exceptiongroup-1.3.1-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2022 Alex Grönholm。
- 来源：[对应来源](https://pypi.org/project/exceptiongroup/1.3.1/)；[对应来源](https://github.com/agronholm/exceptiongroup/blob/main/CHANGES.rst)；[对应来源](https://github.com/agronholm/exceptiongroup/issues)；[对应来源](https://github.com/agronholm/exceptiongroup)。版本依据及SHA见机器索引对应`wheel:wheels/exceptiongroup-1.3.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/exceptiongroup-1.3.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 270. fastapi — 0.141.1

- 范围/位置：B；`wheels/fastapi-0.141.1-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sebastián Ramírez。
- 来源：[对应来源](https://pypi.org/project/fastapi/0.141.1/)；[对应来源](https://github.com/fastapi/fastapi)；[对应来源](https://fastapi.tiangolo.com/)；[对应来源](https://github.com/fastapi/fastapi/issues)；[对应来源](https://fastapi.tiangolo.com/release-notes/)。版本依据及SHA见机器索引对应`wheel:wheels/fastapi-0.141.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/fastapi-0.141.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 271. Flask — 3.1.3

- 范围/位置：B；`wheels/flask-3.1.3-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2010 Pallets。
- 来源：[对应来源](https://pypi.org/project/Flask/3.1.3/)；[对应来源](https://flask.palletsprojects.com/page/changes/)；[对应来源](https://discord.gg/pallets)；[对应来源](https://flask.palletsprojects.com/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://github.com/pallets/flask/)。版本依据及SHA见机器索引对应`wheel:wheels/flask-3.1.3-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/Flask-3.1.3/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 272. fsspec — 2026.7.0

- 范围/位置：B；`wheels/fsspec-2026.7.0-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2018, Martin Durant。
- 来源：[对应来源](https://pypi.org/project/fsspec/2026.7.0/)；[对应来源](https://filesystem-spec.readthedocs.io/en/latest/changelog.html)；[对应来源](https://filesystem-spec.readthedocs.io/en/latest/)；[对应来源](https://github.com/fsspec/filesystem_spec)。版本依据及SHA见机器索引对应`wheel:wheels/fsspec-2026.7.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/fsspec-2026.7.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 273. gradio — 6.17.3

- 范围/位置：B；`wheels/gradio-6.17.3-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：Copyright (c) 2014 Arnout Kazemier；Copyright 2014–present Olivier Lalonde <olalonde@gmail.com>, James Talmage <james@talmage.io>, Ruben Verborgh；Copyright (c) 2010-2016 Charlie Robbins, Jarrett Cruger & the Contributors.；Copyright (c) 2015 Unshift.io, Arnout Kazemier,  the Contributors.。
- 来源：[对应来源](https://pypi.org/project/gradio/6.17.3/)；[对应来源](https://github.com/gradio-app/gradio)。版本依据及SHA见机器索引对应`wheel:wheels/gradio-6.17.3-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/gradio-6.17.3/LICENSE)；[bfa8a54bb9-LICENSE](materials/wheel/gradio-6.17.3/bfa8a54bb9-LICENSE)；[589850dfc0-LICENSE](materials/wheel/gradio-6.17.3/589850dfc0-LICENSE)；[3b2a6a268a-LICENSE](materials/wheel/gradio-6.17.3/3b2a6a268a-LICENSE)；[c71d239df9-LICENSE](materials/wheel/gradio-6.17.3/c71d239df9-LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 274. gradio_client — 2.5.0

- 范围/位置：B；`wheels/gradio_client-2.5.0-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/gradio_client/2.5.0/)；[对应来源](https://github.com/gradio-app/gradio)。版本依据及SHA见机器索引对应`wheel:wheels/gradio_client-2.5.0-py3-none-any.whl`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 275. groovy — 0.1.2

- 范围/位置：B；`wheels/groovy-0.1.2-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/groovy/0.1.2/)；[对应来源](https://github.com/gradio-app/groovy)。版本依据及SHA见机器索引对应`wheel:wheels/groovy-0.1.2-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/groovy-0.1.2/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 276. h11 — 0.16.0

- 范围/位置：B；`wheels/h11-0.16.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2016 Nathaniel J. Smith <njs@pobox.com> and other contributors。
- 来源：[对应来源](https://pypi.org/project/h11/0.16.0/)；[对应来源](https://github.com/python-hyper/h11)。版本依据及SHA见机器索引对应`wheel:wheels/h11-0.16.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/h11-0.16.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 277. hf-gradio — 0.4.1

- 范围/位置：B；`wheels/hf_gradio-0.4.1-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2026 Gradio。
- 来源：[对应来源](https://pypi.org/project/hf-gradio/0.4.1/)；[对应来源](https://github.com/gradio-app/hf-gradio#)。版本依据及SHA见机器索引对应`wheel:wheels/hf_gradio-0.4.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/hf-gradio-0.4.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 278. httpcore — 1.0.9

- 范围/位置：B；`wheels/httpcore-1.0.9-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright © 2020, [Encode OSS Ltd](https://www.encode.io/).。
- 来源：[对应来源](https://pypi.org/project/httpcore/1.0.9/)；[对应来源](https://www.encode.io/httpcore)；[对应来源](https://www.encode.io/httpcore/)；[对应来源](https://github.com/encode/httpcore)。版本依据及SHA见机器索引对应`wheel:wheels/httpcore-1.0.9-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.md](materials/wheel/httpcore-1.0.9/LICENSE.md)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 279. httpx — 0.28.1

- 范围/位置：B；`wheels/httpx-0.28.1-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright © 2019, [Encode OSS Ltd](https://www.encode.io/).。
- 来源：[对应来源](https://pypi.org/project/httpx/0.28.1/)；[对应来源](https://github.com/encode/httpx/blob/master/CHANGELOG.md)；[对应来源](https://www.python-httpx.org)；[对应来源](https://github.com/encode/httpx)。版本依据及SHA见机器索引对应`wheel:wheels/httpx-0.28.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.md](materials/wheel/httpx-0.28.1/LICENSE.md)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 280. huggingface_hub — 0.36.2

- 范围/位置：B；`wheels/huggingface_hub-0.36.2-py3-none-any.whl`。
- 许可：Apache。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/0.36.2/)；[对应来源](https://github.com/huggingface/huggingface_hub)。版本依据及SHA见机器索引对应`wheel:wheels/huggingface_hub-0.36.2-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/huggingface_hub-0.36.2/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 281. huggingface_hub — 1.24.0

- 范围/位置：B；`wheels/huggingface_hub-1.24.0-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/1.24.0/)；[对应来源](https://github.com/huggingface/huggingface_hub)。版本依据及SHA见机器索引对应`wheel:wheels/huggingface_hub-1.24.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/huggingface_hub-1.24.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 282. HyperPyYAML — 1.2.3

- 范围/位置：B；`wheels/hyperpyyaml-1.2.3-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/HyperPyYAML/1.2.3/)；[对应来源](https://github.com/speechbrain/HyperPyYAML)。版本依据及SHA见机器索引对应`wheel:wheels/hyperpyyaml-1.2.3-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/HyperPyYAML-1.2.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 283. itsdangerous — 2.2.0

- 范围/位置：B；`wheels/itsdangerous-2.2.0-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright 2011 Pallets。
- 来源：[对应来源](https://pypi.org/project/itsdangerous/2.2.0/)；[对应来源](https://itsdangerous.palletsprojects.com/changes/)；[对应来源](https://discord.gg/pallets)；[对应来源](https://itsdangerous.palletsprojects.com/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://github.com/pallets/itsdangerous/)。版本依据及SHA见机器索引对应`wheel:wheels/itsdangerous-2.2.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/itsdangerous-2.2.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 284. Jinja2 — 3.1.6

- 范围/位置：B；`wheels/jinja2-3.1.6-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright 2007 Pallets。
- 来源：[对应来源](https://pypi.org/project/Jinja2/3.1.6/)；[对应来源](https://jinja.palletsprojects.com/changes/)；[对应来源](https://discord.gg/pallets)；[对应来源](https://jinja.palletsprojects.com/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://github.com/pallets/jinja/)。版本依据及SHA见机器索引对应`wheel:wheels/jinja2-3.1.6-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/Jinja2-3.1.6/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 285. kaldi-native-fbank — 1.22.3

- 范围/位置：B；`wheels/kaldi_native_fbank-1.22.3-cp310-cp310-win_amd64.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldi-native-fbank/1.22.3/)；[对应来源](https://github.com/csukuangfj/kaldi-native-fbank)。版本依据及SHA见机器索引对应`wheel:wheels/kaldi_native_fbank-1.22.3-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/kaldi-native-fbank-1.22.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 286. kaldiio — 2.18.1

- 范围/位置：B；`wheels/kaldiio-2.18.1-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldiio/2.18.1/)；[对应来源](https://github.com/nttcslab-sp/kaldiio)。版本依据及SHA见机器索引对应`wheel:wheels/kaldiio-2.18.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/kaldiio-2.18.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 287. librosa — 0.11.0

- 范围/位置：B；`wheels/librosa-0.11.0-py3-none-any.whl`。
- 许可：ISC。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/librosa/0.11.0/)；[对应来源](https://librosa.org/doc)；[对应来源](https://github.com/librosa/librosa/releases)；[对应来源](https://github.com/librosa/librosa)；[对应来源](https://github.com/librosa/librosa/issues)；[对应来源](https://groups.google.com/g/librosa)。版本依据及SHA见机器索引对应`wheel:wheels/librosa-0.11.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.md](materials/wheel/librosa-0.11.0/LICENSE.md)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 288. markdown-it-py — 4.2.0

- 范围/位置：B；`wheels/markdown_it_py-4.2.0-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2020 ExecutableBookProject；Copyright (c) 2014 Vitaly Puzrin, Alex Kocharin.。
- 来源：[对应来源](https://pypi.org/project/markdown-it-py/4.2.0/)；[对应来源](https://markdown-it-py.readthedocs.io)；[对应来源](https://github.com/executablebooks/markdown-it-py)。版本依据及SHA见机器索引对应`wheel:wheels/markdown_it_py-4.2.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/markdown-it-py-4.2.0/LICENSE)；[LICENSE.markdown-it](materials/wheel/markdown-it-py-4.2.0/LICENSE.markdown-it)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 289. MarkupSafe — 3.0.3

- 范围/位置：B；`wheels/markupsafe-3.0.3-cp310-cp310-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2010 Pallets。
- 来源：[对应来源](https://pypi.org/project/MarkupSafe/3.0.3/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://markupsafe.palletsprojects.com/)；[对应来源](https://markupsafe.palletsprojects.com/page/changes/)；[对应来源](https://github.com/pallets/markupsafe/)；[对应来源](https://discord.gg/pallets)。版本依据及SHA见机器索引对应`wheel:wheels/markupsafe-3.0.3-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/MarkupSafe-3.0.3/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 290. MarkupSafe — 3.0.3

- 范围/位置：B；`wheels/markupsafe-3.0.3-cp312-cp312-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2010 Pallets。
- 来源：[对应来源](https://pypi.org/project/MarkupSafe/3.0.3/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://markupsafe.palletsprojects.com/)；[对应来源](https://markupsafe.palletsprojects.com/page/changes/)；[对应来源](https://github.com/pallets/markupsafe/)；[对应来源](https://discord.gg/pallets)。版本依据及SHA见机器索引对应`wheel:wheels/markupsafe-3.0.3-cp312-cp312-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/MarkupSafe-3.0.3/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 291. mdurl — 0.1.2

- 范围/位置：B；`wheels/mdurl-0.1.2-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2015 Vitaly Puzrin, Alex Kocharin.；Copyright (c) 2021 Taneli Hukkinen。
- 来源：[对应来源](https://pypi.org/project/mdurl/0.1.2/)；[对应来源](https://github.com/executablebooks/mdurl)。版本依据及SHA见机器索引对应`wheel:wheels/mdurl-0.1.2-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/mdurl-0.1.2/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 292. mpmath — 1.3.0

- 范围/位置：B；`wheels/mpmath-1.3.0-py3-none-any.whl`。
- 许可：BSD。组件版权声明：Copyright (c) 2005-2021 Fredrik Johansson and mpmath contributors。
- 来源：[对应来源](https://pypi.org/project/mpmath/1.3.0/)；[对应来源](https://github.com/fredrik-johansson/mpmath)；[对应来源](https://github.com/fredrik-johansson/mpmath/issues)；[对应来源](http://mpmath.org/doc/current/)。版本依据及SHA见机器索引对应`wheel:wheels/mpmath-1.3.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/mpmath-1.3.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 293. nagisa — 0.2.11

- 范围/位置：B；`wheels/nagisa-0.2.11-cp310-cp310-win_amd64.whl`。
- 许可：MIT License。组件版权声明：Copyright (c) 2018 taishi-i。
- 来源：[对应来源](https://pypi.org/project/nagisa/0.2.11/)；[对应来源](https://github.com/taishi-i/nagisa)。版本依据及SHA见机器索引对应`wheel:wheels/nagisa-0.2.11-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/nagisa-0.2.11/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 294. networkx — 3.4.2

- 范围/位置：B；`wheels/networkx-3.4.2-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (C) 2004-2024, NetworkX Developers。
- 来源：[对应来源](https://pypi.org/project/networkx/3.4.2/)；[对应来源](https://networkx.org/)；[对应来源](https://github.com/networkx/networkx/issues)；[对应来源](https://networkx.org/documentation/stable/)；[对应来源](https://github.com/networkx/networkx)。版本依据及SHA见机器索引对应`wheel:wheels/networkx-3.4.2-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/networkx-3.4.2/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 295. networkx — 3.6.1

- 范围/位置：B；`wheels/networkx-3.6.1-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2004-2025, NetworkX Developers。
- 来源：[对应来源](https://pypi.org/project/networkx/3.6.1/)；[对应来源](https://networkx.org/)；[对应来源](https://github.com/networkx/networkx/issues)；[对应来源](https://networkx.org/documentation/stable/)；[对应来源](https://github.com/networkx/networkx)。版本依据及SHA见机器索引对应`wheel:wheels/networkx-3.6.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/networkx-3.6.1/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 296. numpy — 2.2.6

- 范围/位置：B；`wheels/numpy-2.2.6-cp310-cp310-win_amd64.whl`。
- 许可：Copyright (c) 2005-2024, NumPy Developers. All rights reserved. Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are me。组件版权声明：Copyright (c) 2006, University of Georgia and Pierre G.F. Gerard-Marchant；Copyright (c) 2019 Kevin Sheppard. All rights reserved.；Copyright (c) 2005-2024, NumPy Developers.。
- 来源：[对应来源](https://pypi.org/project/numpy/2.2.6/)；[对应来源](https://numpy.org)；[对应来源](https://numpy.org/doc/)；[对应来源](https://github.com/numpy/numpy)；[对应来源](https://pypi.org/project/numpy/#files)；[对应来源](https://github.com/numpy/numpy/issues)；[对应来源](https://numpy.org/doc/stable/release)。版本依据及SHA见机器索引对应`wheel:wheels/numpy-2.2.6-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/numpy-2.2.6/LICENSE)；[LICENSE.md](materials/wheel/numpy-2.2.6/LICENSE.md)；[LICENSE.txt](materials/wheel/numpy-2.2.6/LICENSE.txt)；[14256cc3a2-LICENSE.txt](materials/wheel/numpy-2.2.6/14256cc3a2-LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 297. pandas — 2.3.3

- 范围/位置：B；`wheels/pandas-2.3.3-cp310-cp310-win_amd64.whl`。
- 许可：BSD 3-Clause License Copyright (c) 2008-2011, AQR Capital Management, LLC, Lambda Foundry, Inc. and PyData Development Team All rights reserved. Copyright (c) 2011-2023, Open source contributors.。组件版权声明：Copyright (c) 2008-2011, AQR Capital Management, LLC, Lambda Foundry, Inc. and PyData Development Team；Copyright (c) 2011-2023, Open source contributors.。
- 来源：[对应来源](https://pypi.org/project/pandas/2.3.3/)；[对应来源](https://pandas.pydata.org)；[对应来源](https://pandas.pydata.org/docs/)；[对应来源](https://github.com/pandas-dev/pandas)。版本依据及SHA见机器索引对应`wheel:wheels/pandas-2.3.3-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/pandas-2.3.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 298. pillow — 12.3.0

- 范围/位置：B；`wheels/pillow-12.3.0-cp310-cp310-win_amd64.whl`。
- 许可：MIT-CMU。组件版权声明：Copyright © 1997-2011 by Secret Labs AB；Copyright © 1995-2011 by Fredrik Lundh and contributors；Copyright © 2010 by Jeffrey 'Alex' Clark and contributors；Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.。
- 来源：[对应来源](https://pypi.org/project/pillow/12.3.0/)；[对应来源](https://pillow.readthedocs.io/en/stable/releasenotes/index.html)；[对应来源](https://github.com/python-pillow/Pillow/releases)；[对应来源](https://pillow.readthedocs.io)；[对应来源](https://tidelift.com/subscription/pkg/pypi-pillow?utm_source=pypi-pillow&utm_medium=pypi)；[对应来源](https://python-pillow.github.io)；[对应来源](https://fosstodon.org/@pillow)；[对应来源](https://github.com/python-pillow/Pillow)。版本依据及SHA见机器索引对应`wheel:wheels/pillow-12.3.0-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/pillow-12.3.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 299. pooch — 1.9.0

- 范围/位置：B；`wheels/pooch-1.9.0-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2018 The Pooch Developers。
- 来源：[对应来源](https://pypi.org/project/pooch/1.9.0/)；[对应来源](https://www.fatiando.org/pooch)；[对应来源](https://www.fatiando.org/pooch/latest/changes.html)；[对应来源](https://github.com/fatiando/pooch/issues)；[对应来源](https://github.com/fatiando/pooch)。版本依据及SHA见机器索引对应`wheel:wheels/pooch-1.9.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/pooch-1.9.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 300. psutil — 7.2.2

- 范围/位置：B；`wheels/psutil-7.2.2-cp37-abi3-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola。
- 来源：[对应来源](https://pypi.org/project/psutil/7.2.2/)；[对应来源](https://github.com/giampaolo/psutil)。版本依据及SHA见机器索引对应`wheel:wheels/psutil-7.2.2-cp37-abi3-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/psutil-7.2.2/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 301. pycparser — 3.0

- 范围/位置：B；`wheels/pycparser-3.0-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2008-2022, Eli Bendersky。
- 来源：[对应来源](https://pypi.org/project/pycparser/3.0/)；[对应来源](https://github.com/eliben/pycparser)。版本依据及SHA见机器索引对应`wheel:wheels/pycparser-3.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/pycparser-3.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 302. pydub — 0.25.1

- 范围/位置：B；`wheels/pydub-0.25.1-py2.py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2011 James Robert, http://jiaaro.com。
- 来源：[对应来源](https://pypi.org/project/pydub/0.25.1/)；[对应来源](http://pydub.com)。版本依据及SHA见机器索引对应`wheel:wheels/pydub-0.25.1-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/pydub-0.25.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 303. python-dateutil — 2.9.0.post0

- 范围/位置：B；`wheels/python_dateutil-2.9.0.post0-py2.py3-none-any.whl`。
- 许可：Dual License。组件版权声明：Copyright 2017- Paul Ganssle <paul@ganssle.io>；Copyright 2017- dateutil contributors (see AUTHORS file)；Copyright (c) 2003-2011 - Gustavo Niemeyer <gustavo@niemeyer.net>；Copyright (c) 2012-2014 - Tomi Pieviläinen <tomi.pievilainen@iki.fi>；Copyright (c) 2014-2016 - Yaron de Leeuw <me@jarondl.net>；Copyright (c) 2015-     - Paul Ganssle <paul@ganssle.io>；Copyright (c) 2015-     - dateutil contributors (see AUTHORS file)。
- 来源：[对应来源](https://pypi.org/project/python-dateutil/2.9.0.post0/)；[对应来源](https://dateutil.readthedocs.io/en/stable/)；[对应来源](https://github.com/dateutil/dateutil)。版本依据及SHA见机器索引对应`wheel:wheels/python_dateutil-2.9.0.post0-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/python-dateutil-2.9.0.post0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 304. python-multipart — 0.0.32

- 范围/位置：B；`wheels/python_multipart-0.0.32-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/python-multipart/0.0.32/)；[对应来源](https://github.com/Kludex/python-multipart)；[对应来源](https://kludex.github.io/python-multipart/)；[对应来源](https://github.com/Kludex/python-multipart/blob/master/CHANGELOG.md)。版本依据及SHA见机器索引对应`wheel:wheels/python_multipart-0.0.32-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/python-multipart-0.0.32/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 305. PyYAML — 6.0.3

- 范围/位置：B；`wheels/pyyaml-6.0.3-cp310-cp310-win_amd64.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2017-2021 Ingy döt Net；Copyright (c) 2006-2016 Kirill Simonov。
- 来源：[对应来源](https://pypi.org/project/PyYAML/6.0.3/)；[对应来源](https://github.com/yaml/pyyaml/issues)；[对应来源](https://github.com/yaml/pyyaml/actions)；[对应来源](https://pyyaml.org/wiki/PyYAMLDocumentation)；[对应来源](http://lists.sourceforge.net/lists/listinfo/yaml-core)；[对应来源](https://github.com/yaml/pyyaml)。版本依据及SHA见机器索引对应`wheel:wheels/pyyaml-6.0.3-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/PyYAML-6.0.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 306. PyYAML — 6.0.3

- 范围/位置：B；`wheels/pyyaml-6.0.3-cp312-cp312-win_amd64.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2017-2021 Ingy döt Net；Copyright (c) 2006-2016 Kirill Simonov。
- 来源：[对应来源](https://pypi.org/project/PyYAML/6.0.3/)；[对应来源](https://github.com/yaml/pyyaml/issues)；[对应来源](https://github.com/yaml/pyyaml/actions)；[对应来源](https://pyyaml.org/wiki/PyYAMLDocumentation)；[对应来源](http://lists.sourceforge.net/lists/listinfo/yaml-core)；[对应来源](https://github.com/yaml/pyyaml)。版本依据及SHA见机器索引对应`wheel:wheels/pyyaml-6.0.3-cp312-cp312-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/PyYAML-6.0.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 307. qwen-asr — 0.0.6

- 范围/位置：B；`wheels/qwen_asr-0.0.6-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/qwen-asr/0.0.6/)；[对应来源](https://github.com/Qwen/Qwen3-ASR)。版本依据及SHA见机器索引对应`wheel:wheels/qwen_asr-0.0.6-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/qwen-asr-0.0.6/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 308. qwen-omni-utils — 0.0.9

- 范围/位置：B；`wheels/qwen_omni_utils-0.0.9-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/qwen-omni-utils/0.0.9/)；[对应来源](https://github.com/QwenLM/Qwen2-VL/tree/main/qwen-vl-utils)；[对应来源](https://github.com/QwenLM/Qwen2-VL.git)；[对应来源](https://github.com/QwenLM/Qwen2-VL/issues)。版本依据及SHA见机器索引对应`wheel:wheels/qwen_omni_utils-0.0.9-py3-none-any.whl`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 309. requests — 2.33.0

- 范围/位置：B；`wheels/requests-2.33.0-py3-none-any.whl`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/requests/2.33.0/)；[对应来源](https://requests.readthedocs.io)；[对应来源](https://github.com/psf/requests)。版本依据及SHA见机器索引对应`wheel:wheels/requests-2.33.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/requests-2.33.0/LICENSE)；[NOTICE](materials/wheel/requests-2.33.0/NOTICE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 310. rich — 15.0.0

- 范围/位置：B；`wheels/rich-15.0.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Will McGugan。
- 来源：[对应来源](https://pypi.org/project/rich/15.0.0/)；[对应来源](https://rich.readthedocs.io/en/latest/)；[对应来源](https://github.com/Textualize/rich)。版本依据及SHA见机器索引对应`wheel:wheels/rich-15.0.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/rich-15.0.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 311. ruamel.yaml — 0.18.17

- 范围/位置：B；`wheels/ruamel_yaml-0.18.17-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2014-2025 Anthon van der Neut, Ruamel bvba。
- 来源：[对应来源](https://pypi.org/project/ruamel.yaml/0.18.17/)；[对应来源](https://sourceforge.net/p/ruamel-yaml/)；[对应来源](https://sourceforge.net/p/ruamel-yaml/code/ci/default/tree/)；[对应来源](https://sourceforge.net/p/ruamel-yaml/tickets/)；[对应来源](https://yaml.dev/doc/ruamel.yaml)。版本依据及SHA见机器索引对应`wheel:wheels/ruamel_yaml-0.18.17-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/ruamel.yaml-0.18.17/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 312. ruamel.yaml.clib — 0.2.15

- 范围/位置：B；`wheels/ruamel_yaml_clib-0.2.15-cp310-cp310-win_amd64.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2019-2025 Anthon van der Neut, Ruamel bvba。
- 来源：[对应来源](https://pypi.org/project/ruamel.yaml.clib/0.2.15/)；[对应来源](https://sourceforge.net/p/ruamel-yaml-clib/)；[对应来源](https://sourceforge.net/p/ruamel-yaml-clib/code/ci/default/tree/)；[对应来源](https://sourceforge.net/p/ruamel-yaml-clib/tickets/)；[对应来源](https://yaml.dev/doc/ruamel.yaml.clib/)。版本依据及SHA见机器索引对应`wheel:wheels/ruamel_yaml_clib-0.2.15-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/ruamel.yaml.clib-0.2.15/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 313. safehttpx — 0.1.7

- 范围/位置：B；`wheels/safehttpx-0.1.7-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safehttpx/0.1.7/)；[对应来源](https://github.com/gradio-app/safehttpx)。版本依据及SHA见机器索引对应`wheel:wheels/safehttpx-0.1.7-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/safehttpx-0.1.7/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 314. safetensors — 0.8.0

- 范围/位置：B；`wheels/safetensors-0.8.0-cp310-abi3-win_amd64.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)；[对应来源](https://github.com/huggingface/safetensors)。版本依据及SHA见机器索引对应`wheel:wheels/safetensors-0.8.0-cp310-abi3-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/safetensors-0.8.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 315. scikit-learn — 1.7.2

- 范围/位置：B；`wheels/scikit_learn-1.7.2-cp310-cp310-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2007-2024 The scikit-learn developers.；Copyright (c) 2022 Consortium for Python Data API Standards；Copyright (c) 2024 Consortium for Python Data API Standards。
- 来源：[对应来源](https://pypi.org/project/scikit-learn/1.7.2/)；[对应来源](https://scikit-learn.org)；[对应来源](https://github.com/scikit-learn/scikit-learn)；[对应来源](https://pypi.org/project/scikit-learn/#files)；[对应来源](https://github.com/scikit-learn/scikit-learn/issues)；[对应来源](https://scikit-learn.org/stable/whats_new)。版本依据及SHA见机器索引对应`wheel:wheels/scikit_learn-1.7.2-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[COPYING](materials/wheel/scikit-learn-1.7.2/COPYING)；[LICENSE](materials/wheel/scikit-learn-1.7.2/LICENSE)；[8b2e8a4aa8-LICENSE](materials/wheel/scikit-learn-1.7.2/8b2e8a4aa8-LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 316. scipy — 1.15.3

- 范围/位置：B；`wheels/scipy-1.15.3-cp310-cp310-win_amd64.whl`。
- 许可：Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers. All rights reserved. Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following。组件版权声明：Copyright (C) 2010-2019 Max-Planck-Society；Copyright (c) 1996-2008 Rice University.；Copyright (c) 2001-2011 - Scilab Enterprises；Copyright (c) 2010 - Jordi Gutiérrez Hermoso (Octave patch)；Copyright (c) 2007 - Sébastien Fabbro (gentoo patch)；Copyright (c) 2018, Quansight-Labs；Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers.。
- 来源：[对应来源](https://pypi.org/project/scipy/1.15.3/)；[对应来源](https://scipy.org/)；[对应来源](https://docs.scipy.org/doc/scipy/)；[对应来源](https://github.com/scipy/scipy)；[对应来源](https://github.com/scipy/scipy/releases)；[对应来源](https://github.com/scipy/scipy/issues)。版本依据及SHA见机器索引对应`wheel:wheels/scipy-1.15.3-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE.md](materials/wheel/scipy-1.15.3/LICENSE.md)；[COPYING](materials/wheel/scipy-1.15.3/COPYING)；[COPYING.txt](materials/wheel/scipy-1.15.3/COPYING.txt)；[LICENSE](materials/wheel/scipy-1.15.3/LICENSE)；[LICENSE.txt](materials/wheel/scipy-1.15.3/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 317. semantic-version — 2.10.0

- 范围/位置：B；`wheels/semantic_version-2.10.0-py2.py3-none-any.whl`。
- 许可：BSD。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/semantic-version/2.10.0/)；[对应来源](https://github.com/rbarrois/python-semanticversion)。版本依据及SHA见机器索引对应`wheel:wheels/semantic_version-2.10.0-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/semantic-version-2.10.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 318. sentencepiece — 0.2.2

- 范围/位置：B；`wheels/sentencepiece-0.2.2-cp310-cp310-win_amd64.whl`。
- 许可：Apache-2.0。组件版权声明：Copyright (c) 2008-2011, Susumu Yata；Copyright (c) 2010 Daisuke Okanohara All Rights Reserved.；Copyright 2008 Google Inc.  All rights reserved.。
- 来源：[对应来源](https://pypi.org/project/sentencepiece/0.2.2/)；[对应来源](https://github.com/google/sentencepiece)。版本依据及SHA见机器索引对应`wheel:wheels/sentencepiece-0.2.2-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[54da7462-LICENSE](materials/python-exact/sentencepiece-0.2.2/54da7462-LICENSE)；[85a162a6-LICENSE](materials/python-exact/sentencepiece-0.2.2/85a162a6-LICENSE)；[8e314a11-LICENSE](materials/python-exact/sentencepiece-0.2.2/8e314a11-LICENSE)；[ba5b4c16-LICENSE](materials/python-exact/sentencepiece-0.2.2/ba5b4c16-LICENSE)；[7d606f49-LICENSE](materials/python-exact/sentencepiece-0.2.2/7d606f49-LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 319. setuptools — 80.9.0

- 范围/位置：B；`wheels/setuptools-80.9.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2010-202x The platformdirs developers；Copyright (c) 2018, Michal Horejsek；Copyright (c) 2012 Erik Rose；Copyright (c) 2021 Taneli Hukkinen；Copyright (c) 2012 Daniel Holth <dholth@fastmail.fm> and contributors。
- 来源：[对应来源](https://pypi.org/project/setuptools/80.9.0/)；[对应来源](https://github.com/pypa/setuptools)；[对应来源](https://setuptools.pypa.io/)；[对应来源](https://setuptools.pypa.io/en/stable/history.html)。版本依据及SHA见机器索引对应`wheel:wheels/setuptools-80.9.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/setuptools-80.9.0/LICENSE)；[cad1ef5bd3-LICENSE](materials/wheel/setuptools-80.9.0/cad1ef5bd3-LICENSE)；[LICENSE.APACHE](materials/wheel/setuptools-80.9.0/LICENSE.APACHE)；[LICENSE.BSD](materials/wheel/setuptools-80.9.0/LICENSE.BSD)；[NOTICE](materials/wheel/setuptools-80.9.0/NOTICE)；[5d300dbfa6-NOTICE](materials/wheel/setuptools-80.9.0/5d300dbfa6-NOTICE)；[86da0f01ae-LICENSE](materials/wheel/setuptools-80.9.0/86da0f01ae-LICENSE)；[ade78d0498-LICENSE](materials/wheel/setuptools-80.9.0/ade78d0498-LICENSE)；[cfc7749b96-LICENSE](materials/wheel/setuptools-80.9.0/cfc7749b96-LICENSE)；[09f1c8c9e9-LICENSE](materials/wheel/setuptools-80.9.0/09f1c8c9e9-LICENSE)；[b80816b0d5-LICENSE](materials/wheel/setuptools-80.9.0/b80816b0d5-LICENSE)；[6163f7987d-LICENSE](materials/wheel/setuptools-80.9.0/6163f7987d-LICENSE)；[3b2f81fe21-LICENSE](materials/wheel/setuptools-80.9.0/3b2f81fe21-LICENSE)；[LICENSE.txt](materials/wheel/setuptools-80.9.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 320. shellingham — 1.5.4

- 范围/位置：B；`wheels/shellingham-1.5.4-py2.py3-none-any.whl`。
- 许可：ISC License。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/shellingham/1.5.4/)；[对应来源](https://github.com/sarugaku/shellingham)。版本依据及SHA见机器索引对应`wheel:wheels/shellingham-1.5.4-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/shellingham-1.5.4/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 321. six — 1.17.0

- 范围/位置：B；`wheels/six-1.17.0-py2.py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2010-2024 Benjamin Peterson。
- 来源：[对应来源](https://pypi.org/project/six/1.17.0/)；[对应来源](https://github.com/benjaminp/six)。版本依据及SHA见机器索引对应`wheel:wheels/six-1.17.0-py2.py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/six-1.17.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 322. soundfile — 0.14.0

- 范围/位置：B；`wheels/soundfile-0.14.0-py2.py3-none-win_amd64.whl`。
- 许可：BSD 3-Clause License。组件版权声明：Copyright (c) 2013, Bastian Bechtold。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.14.0/)；[对应来源](https://github.com/bastibe/python-soundfile)。版本依据及SHA见机器索引对应`wheel:wheels/soundfile-0.14.0-py2.py3-none-win_amd64.whl`。
- 完整原文及现有材料：[COPYING](materials/wheel/soundfile-0.14.0/COPYING)；[license_notes.md](materials/wheel/soundfile-0.14.0/license_notes.md)；[LICENSE](materials/wheel/soundfile-0.14.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 323. soxr — 1.1.0

- 范围/位置：B；`wheels/soxr-1.1.0-cp310-cp310-win_amd64.whl`。
- 许可：LGPL-2.1-or-later。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soxr/1.1.0/)；[对应来源](https://github.com/dofuuz/python-soxr)；[对应来源](https://python-soxr.readthedocs.io)；[对应来源](https://github.com/dofuuz/python-soxr/releases)；[对应来源](https://github.com/dofuuz/python-soxr/issues)。版本依据及SHA见机器索引对应`wheel:wheels/soxr-1.1.0-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[COPYING.LGPL](materials/wheel/soxr-1.1.0/COPYING.LGPL)；[LICENSE-libsoxr.txt](materials/wheel/soxr-1.1.0/LICENSE-libsoxr.txt)；[LICENSE-PFFFT.txt](materials/wheel/soxr-1.1.0/LICENSE-PFFFT.txt)；[LICENSE.txt](materials/wheel/soxr-1.1.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 324. soxr — 1.1.0

- 范围/位置：B；`wheels/soxr-1.1.0-cp312-abi3-win_amd64.whl`。
- 许可：LGPL-2.1-or-later。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soxr/1.1.0/)；[对应来源](https://github.com/dofuuz/python-soxr)；[对应来源](https://python-soxr.readthedocs.io)；[对应来源](https://github.com/dofuuz/python-soxr/releases)；[对应来源](https://github.com/dofuuz/python-soxr/issues)。版本依据及SHA见机器索引对应`wheel:wheels/soxr-1.1.0-cp312-abi3-win_amd64.whl`。
- 完整原文及现有材料：[COPYING.LGPL](materials/wheel/soxr-1.1.0/COPYING.LGPL)；[LICENSE-libsoxr.txt](materials/wheel/soxr-1.1.0/LICENSE-libsoxr.txt)；[LICENSE-PFFFT.txt](materials/wheel/soxr-1.1.0/LICENSE-PFFFT.txt)；[LICENSE.txt](materials/wheel/soxr-1.1.0/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 325. soynlp — 0.0.493

- 范围/位置：B；`wheels/soynlp-0.0.493-py3-none-any.whl`。
- 许可：UNKNOWN。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soynlp/0.0.493/)；[对应来源](https://github.com/lovit/soynlp)。版本依据及SHA见机器索引对应`wheel:wheels/soynlp-0.0.493-py3-none-any.whl`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 326. speechbrain — 1.0.3

- 范围/位置：B；`wheels/speechbrain-1.0.3-py3-none-any.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/speechbrain/1.0.3/)；[对应来源](https://speechbrain.github.io/)。版本依据及SHA见机器索引对应`wheel:wheels/speechbrain-1.0.3-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/speechbrain-1.0.3/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 327. sympy — 1.14.0

- 范围/位置：B；`wheels/sympy-1.14.0-py3-none-any.whl`。
- 许可：BSD。组件版权声明：Copyright 2016, latex2sympy；Copyright (c) 2006-2023 SymPy Development Team。
- 来源：[对应来源](https://pypi.org/project/sympy/1.14.0/)；[对应来源](https://github.com/sympy/sympy)。版本依据及SHA见机器索引对应`wheel:wheels/sympy-1.14.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/sympy-1.14.0/LICENSE.txt)；[LICENSE](materials/wheel/sympy-1.14.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 328. tokenizers — 0.22.2

- 范围/位置：B；`wheels/tokenizers-0.22.2-cp39-abi3-win_amd64.whl`。
- 许可：元数据未声明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)；[对应来源](https://github.com/huggingface/tokenizers)。版本依据及SHA见机器索引对应`wheel:wheels/tokenizers-0.22.2-cp39-abi3-win_amd64.whl`。
- 完整原文及现有材料：[ce7b22be-LICENSE](materials/python-exact/tokenizers-0.22.2/ce7b22be-LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 329. tomlkit — 0.14.0

- 范围/位置：B；`wheels/tomlkit-0.14.0-py3-none-any.whl`。
- 许可：MIT。组件版权声明：Copyright (c) 2018 Sébastien Eustace。
- 来源：[对应来源](https://pypi.org/project/tomlkit/0.14.0/)；[对应来源](https://github.com/sdispater/tomlkit)。版本依据及SHA见机器索引对应`wheel:wheels/tomlkit-0.14.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/tomlkit-0.14.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 330. torch — 2.11.0+cpu

- 范围/位置：B；`wheels/torch-2.11.0+cpu-cp310-cp310-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2016-     Facebook, Inc            (Adam Paszke)；Copyright (c) 2014-     Facebook, Inc            (Soumith Chintala)；Copyright (c) 2011-2014 Idiap Research Institute (Ronan Collobert)；Copyright (c) 2012-2014 Deepmind Technologies    (Koray Kavukcuoglu)；Copyright (c) 2011-2012 NEC Laboratories America (Koray Kavukcuoglu)；Copyright (c) 2011-2013 NYU                      (Clement Farabet)；Copyright (c) 2006-2010 NEC Laboratories America (Ronan Collobert, Leon Bottou, Iain Melvin, Jason Weston)；Copyright (c) 2006      Idiap Research Institute (Samy Bengio)；Copyright (c) 2001-2004 Idiap Research Institute (Ronan Collobert, Samy Bengio, Johnny Mariethoz)；Copyright (c) 2016-present, Facebook Inc. All rights reserved.；Copyright (c) 2016 Facebook Inc.；Copyright (c) 2015 Google Inc.；Copyright (c) 2015 Yangqing Jia；Copyright 2019-2020 Kakao Brain；Copyright (c) 2022 Cruise LLC.；Copyright (c) 2024 Tri Dao.；Copyright (c) 2021, 2023-2025 Arm Limited and/or its affiliates；Copyright(c) 2013, 2014, 2015, the respective contributors；Copyright(c) 2015, 2016 the respective contributors。
- 来源：[对应来源](https://pypi.org/project/torch/2.11.0%2Bcpu/)；[对应来源](https://pytorch.org)；[对应来源](https://github.com/pytorch/pytorch)；[对应来源](https://pytorch.org/docs)；[对应来源](https://github.com/pytorch/pytorch/issues)；[对应来源](https://discuss.pytorch.org)。版本依据及SHA见机器索引对应`wheel:wheels/torch-2.11.0+cpu-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/torch-2.11.0_cpu/LICENSE)；[NOTICE](materials/wheel/torch-2.11.0_cpu/NOTICE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：BSD式主许可及wheel内完整第三方许可/NOTICE；逐项识别内嵌本地库。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：实际附带CPU wheel；不要写成未附带PyTorch，也不要将构建机cu128许可误报为CUDA二进制已附带。

## 331. torch — 2.11.0+cpu

- 范围/位置：B；`wheels/torch-2.11.0+cpu-cp312-cp312-win_amd64.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2016-     Facebook, Inc            (Adam Paszke)；Copyright (c) 2014-     Facebook, Inc            (Soumith Chintala)；Copyright (c) 2011-2014 Idiap Research Institute (Ronan Collobert)；Copyright (c) 2012-2014 Deepmind Technologies    (Koray Kavukcuoglu)；Copyright (c) 2011-2012 NEC Laboratories America (Koray Kavukcuoglu)；Copyright (c) 2011-2013 NYU                      (Clement Farabet)；Copyright (c) 2006-2010 NEC Laboratories America (Ronan Collobert, Leon Bottou, Iain Melvin, Jason Weston)；Copyright (c) 2006      Idiap Research Institute (Samy Bengio)；Copyright (c) 2001-2004 Idiap Research Institute (Ronan Collobert, Samy Bengio, Johnny Mariethoz)；Copyright (c) 2016-present, Facebook Inc. All rights reserved.；Copyright (c) 2016 Facebook Inc.；Copyright (c) 2015 Google Inc.；Copyright (c) 2015 Yangqing Jia；Copyright 2019-2020 Kakao Brain；Copyright (c) 2022 Cruise LLC.；Copyright (c) 2024 Tri Dao.；Copyright (c) 2021, 2023-2025 Arm Limited and/or its affiliates；Copyright(c) 2013, 2014, 2015, the respective contributors；Copyright(c) 2015, 2016 the respective contributors。
- 来源：[对应来源](https://pypi.org/project/torch/2.11.0%2Bcpu/)；[对应来源](https://pytorch.org)；[对应来源](https://github.com/pytorch/pytorch)；[对应来源](https://pytorch.org/docs)；[对应来源](https://github.com/pytorch/pytorch/issues)；[对应来源](https://discuss.pytorch.org)。版本依据及SHA见机器索引对应`wheel:wheels/torch-2.11.0+cpu-cp312-cp312-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/torch-2.11.0_cpu/LICENSE)；[NOTICE](materials/wheel/torch-2.11.0_cpu/NOTICE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：BSD式主许可及wheel内完整第三方许可/NOTICE；逐项识别内嵌本地库。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：实际附带CPU wheel；不要写成未附带PyTorch，也不要将构建机cu128许可误报为CUDA二进制已附带。

## 332. torchaudio — 2.11.0+cpu

- 范围/位置：B；`wheels/torchaudio-2.11.0+cpu-cp310-cp310-win_amd64.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2017 Facebook Inc. (Soumith Chintala),。
- 来源：[对应来源](https://pypi.org/project/torchaudio/2.11.0%2Bcpu/)；[对应来源](https://github.com/pytorch/audio)。版本依据及SHA见机器索引对应`wheel:wheels/torchaudio-2.11.0+cpu-cp310-cp310-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/torchaudio-2.11.0_cpu/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：BSD式主许可及wheel内完整第三方许可/NOTICE；逐项识别内嵌本地库。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：实际附带CPU wheel；不要写成未附带PyTorch，也不要将构建机cu128许可误报为CUDA二进制已附带。

## 333. torchaudio — 2.11.0+cpu

- 范围/位置：B；`wheels/torchaudio-2.11.0+cpu-cp312-cp312-win_amd64.whl`。
- 许可：元数据未声明。组件版权声明：Copyright (c) 2017 Facebook Inc. (Soumith Chintala),。
- 来源：[对应来源](https://pypi.org/project/torchaudio/2.11.0%2Bcpu/)；[对应来源](https://github.com/pytorch/audio)。版本依据及SHA见机器索引对应`wheel:wheels/torchaudio-2.11.0+cpu-cp312-cp312-win_amd64.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/torchaudio-2.11.0_cpu/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：BSD式主许可及wheel内完整第三方许可/NOTICE；逐项识别内嵌本地库。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：实际附带CPU wheel；不要写成未附带PyTorch，也不要将构建机cu128许可误报为CUDA二进制已附带。

## 334. transformers — 4.57.6

- 范围/位置：B；`wheels/transformers-4.57.6-py3-none-any.whl`。
- 许可：Apache 2.0 License。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/4.57.6/)；[对应来源](https://github.com/huggingface/transformers)。版本依据及SHA见机器索引对应`wheel:wheels/transformers-4.57.6-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/transformers-4.57.6/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 335. transformers — 5.14.1

- 范围/位置：B；`wheels/transformers-5.14.1-py3-none-any.whl`。
- 许可：Apache 2.0 License。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/5.14.1/)；[对应来源](https://github.com/huggingface/transformers)。版本依据及SHA见机器索引对应`wheel:wheels/transformers-5.14.1-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/transformers-5.14.1/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 336. typing_extensions — 4.16.0

- 范围/位置：B；`wheels/typing_extensions-4.16.0-py3-none-any.whl`。
- 许可：PSF-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/typing_extensions/4.16.0/)；[对应来源](https://github.com/python/typing_extensions/issues)；[对应来源](https://github.com/python/typing_extensions/blob/main/CHANGELOG.md)；[对应来源](https://typing-extensions.readthedocs.io/)；[对应来源](https://github.com/python/typing_extensions)；[对应来源](https://github.com/python/typing/discussions)。版本依据及SHA见机器索引对应`wheel:wheels/typing_extensions-4.16.0-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE](materials/wheel/typing_extensions-4.16.0/LICENSE)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 337. Werkzeug — 3.1.8

- 范围/位置：B；`wheels/werkzeug-3.1.8-py3-none-any.whl`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2007 Pallets。
- 来源：[对应来源](https://pypi.org/project/Werkzeug/3.1.8/)；[对应来源](https://werkzeug.palletsprojects.com/page/changes/)；[对应来源](https://discord.gg/pallets)；[对应来源](https://werkzeug.palletsprojects.com/)；[对应来源](https://palletsprojects.com/donate)；[对应来源](https://github.com/pallets/werkzeug/)。版本依据及SHA见机器索引对应`wheel:wheels/werkzeug-3.1.8-py3-none-any.whl`。
- 完整原文及现有材料：[LICENSE.txt](materials/wheel/Werkzeug-3.1.8/LICENSE.txt)
- 用途/集成：原wheel归档随包，模型准备时安装到私有Python环境；修改/补丁：80个归档均匹配随包model_wheels.json的SHA256；不等于全部逐一重验上游。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 338. aliyun-python-sdk-core — 2.16.0

- 范围/位置：B；`2ByteASR.exe!PYZ:aliyunsdkcore`、`aliyunsdkcore/`。
- 许可：Apache License 2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/aliyun-python-sdk-core/2.16.0/)。版本依据及SHA见机器索引对应`frozen:aliyun-python-sdk-core`。
- 完整原文及现有材料：[LICENSE](materials/frozen/aliyun-python-sdk-core-2.16.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 339. aliyun-python-sdk-kms — 2.16.5

- 范围/位置：B；`2ByteASR.exe!PYZ:aliyunsdkkms`、`aliyunsdkkms/`。
- 许可：Apache。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/aliyun-python-sdk-kms/2.16.5/)。版本依据及SHA见机器索引对应`frozen:aliyun-python-sdk-kms`。
- 完整原文及现有材料：[LICENSE](materials/frozen/aliyun-python-sdk-kms-2.16.5/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 340. attrs — 26.1.0

- 范围/位置：B；`2ByteASR.exe!PYZ:attrs`、`attrs/`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 Hynek Schlawack and the attrs contributors。
- 来源：[对应来源](https://pypi.org/project/attrs/26.1.0/)。版本依据及SHA见机器索引对应`frozen:attrs`。
- 完整原文及现有材料：[LICENSE](materials/frozen/attrs-26.1.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 341. av — 17.1.0

- 范围/位置：B；`2ByteASR.exe!PYZ:av`、`av/`。
- 许可：BSD-3-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/av/17.1.0/)。版本依据及SHA见机器索引对应`frozen:av`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/av-17.1.0/LICENSE.txt)；[pyav-source.tar.gz](source-materials/pyav-17.1.0/pyav-source.tar.gz)；[pyav-ffmpeg-build-source.tar.gz](source-materials/pyav-17.1.0/pyav-ffmpeg-build-source.tar.gz)；[ffmpeg-source.tar.xz](source-materials/pyav-17.1.0/ffmpeg-source.tar.xz)；[COPYING.LGPLv2.1](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv2.1)；[COPYING.GPLv2](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv2)；[COPYING.LGPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv3)；[COPYING.GPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv3)；[x264-source.tar.bz2](source-materials/pyav-17.1.0/x264-source.tar.bz2)；[COPYING](materials/pyav-codecs/x264-source/COPYING)；[x265-source.tar.gz](source-materials/pyav-17.1.0/x265-source.tar.gz)；[COPYING](materials/pyav-codecs/x265-source/COPYING)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位；新增：pyav-ffmpeg README写x264 32c3b801，但pkg.py固定b35605ac；后者源码SHA已匹配上游脚本，DLL源码对应关系仍未闭合。x2654.2源码和原文已取得，不等于组合授权问题已解决。。

## 342. brotli — 1.2.0

- 范围/位置：B；`2ByteASR.exe!PYZ:brotli`、`brotli/`。
- 许可：MIT。组件版权声明：Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.。
- 来源：[对应来源](https://pypi.org/project/brotli/1.2.0/)。版本依据及SHA见机器索引对应`frozen:brotli`。
- 完整原文及现有材料：[LICENSE](materials/frozen/brotli-1.2.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 343. certifi — 2026.7.22

- 范围/位置：B；`2ByteASR.exe!PYZ:certifi`、`certifi/`。
- 许可：MPL-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/certifi/2026.7.22/)。版本依据及SHA见机器索引对应`frozen:certifi`。
- 完整原文及现有材料：[LICENSE](materials/frozen/certifi-2026.7.22/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 344. cffi — 2.1.0

- 范围/位置：B；`2ByteASR.exe!PYZ:cffi`、`cffi/`。
- 许可：MIT-0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/cffi/2.1.0/)。版本依据及SHA见机器索引对应`frozen:cffi`。
- 完整原文及现有材料：[LICENSE](materials/frozen/cffi-2.1.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 345. charset-normalizer — 3.4.9

- 范围/位置：B；`2ByteASR.exe!PYZ:charset_normalizer`、`charset_normalizer/`。
- 许可：MIT。组件版权声明：Copyright (c) 2025 TAHRI Ahmed R.。
- 来源：[对应来源](https://pypi.org/project/charset-normalizer/3.4.9/)。版本依据及SHA见机器索引对应`frozen:charset-normalizer`。
- 完整原文及现有材料：[LICENSE](materials/frozen/charset-normalizer-3.4.9/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 346. colorama — 0.4.6

- 范围/位置：B；`2ByteASR.exe!PYZ:colorama`、`colorama/`。
- 许可：未声明。组件版权声明：Copyright (c) 2010 Jonathan Hartley。
- 来源：[对应来源](https://pypi.org/project/colorama/0.4.6/)。版本依据及SHA见机器索引对应`frozen:colorama`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/colorama-0.4.6/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 347. comtypes — 1.4.16

- 范围/位置：B；`2ByteASR.exe!PYZ:comtypes`、`comtypes/`。
- 许可：MIT。组件版权声明：Copyright (c) 2006-2013, Thomas Heller.；Copyright (c) 2014, Comtypes Developers.。
- 来源：[对应来源](https://pypi.org/project/comtypes/1.4.16/)。版本依据及SHA见机器索引对应`frozen:comtypes`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/comtypes-1.4.16/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 348. crcmod — 1.7

- 范围/位置：B；`2ByteASR.exe!PYZ:crcmod`、`crcmod/`。
- 许可：MIT。组件版权声明：Copyright (c) 2010  Raymond L. Buvel；Copyright (c) 2010  Craig McQueen。
- 来源：[对应来源](https://pypi.org/project/crcmod/1.7/)。版本依据及SHA见机器索引对应`frozen:crcmod`。
- 完整原文及现有材料：[LICENSE](materials/frozen/crcmod-1.7/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 349. cryptography — 50.0.0

- 范围/位置：B；`2ByteASR.exe!PYZ:cryptography`、`cryptography/`。
- 许可：Apache-2.0 OR BSD-3-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/cryptography/50.0.0/)。版本依据及SHA见机器索引对应`frozen:cryptography`。
- 完整原文及现有材料：[LICENSE](materials/frozen/cryptography-50.0.0/LICENSE)；[LICENSE.APACHE](materials/frozen/cryptography-50.0.0/LICENSE.APACHE)；[LICENSE.BSD](materials/frozen/cryptography-50.0.0/LICENSE.BSD)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 350. Cython — 3.2.9

- 范围/位置：B；`2ByteASR.exe!PYZ:cython`、`cython/`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/Cython/3.2.9/)。版本依据及SHA见机器索引对应`frozen:Cython`。
- 完整原文及现有材料：[898377e0-COPYING.txt](materials/python-exact/Cython-3.2.9/898377e0-COPYING.txt)；[4adcfb77-LICENSE.txt](materials/python-exact/Cython-3.2.9/4adcfb77-LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 351. idna — 3.18

- 范围/位置：B；`2ByteASR.exe!PYZ:idna`、`idna/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2013-2026, Kim Davies and contributors.。
- 来源：[对应来源](https://pypi.org/project/idna/3.18/)。版本依据及SHA见机器索引对应`frozen:idna`。
- 完整原文及现有材料：[LICENSE.md](materials/frozen/idna-3.18/LICENSE.md)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 352. jieba — 0.42.1

- 范围/位置：B；`2ByteASR.exe!PYZ:jieba`、`jieba/`。
- 许可：MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/jieba/0.42.1/)。版本依据及SHA见机器索引对应`frozen:jieba`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 353. jmespath — 0.10.0

- 范围/位置：B；`2ByteASR.exe!PYZ:jmespath`、`jmespath/`。
- 许可：MIT。组件版权声明：Copyright (c) 2013 Amazon.com, Inc. or its affiliates.  All Rights Reserved。
- 来源：[对应来源](https://pypi.org/project/jmespath/0.10.0/)。版本依据及SHA见机器索引对应`frozen:jmespath`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/jmespath-0.10.0/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 354. jsonschema — 4.26.0

- 范围/位置：B；`2ByteASR.exe!PYZ:jsonschema`、`jsonschema/`。
- 许可：MIT。组件版权声明：Copyright (c) 2013 Julian Berman。
- 来源：[对应来源](https://pypi.org/project/jsonschema/4.26.0/)。版本依据及SHA见机器索引对应`frozen:jsonschema`。
- 完整原文及现有材料：[COPYING](materials/frozen/jsonschema-4.26.0/COPYING)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 355. jsonschema-specifications — 2025.9.1

- 范围/位置：B；`2ByteASR.exe!PYZ:jsonschema_specifications`、`jsonschema_specifications/`。
- 许可：MIT。组件版权声明：Copyright (c) 2022 Julian Berman。
- 来源：[对应来源](https://pypi.org/project/jsonschema-specifications/2025.9.1/)。版本依据及SHA见机器索引对应`frozen:jsonschema-specifications`。
- 完整原文及现有材料：[COPYING](materials/frozen/jsonschema-specifications-2025.9.1/COPYING)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 356. MarkupSafe — 3.0.3

- 范围/位置：B；`2ByteASR.exe!PYZ:markupsafe`、`markupsafe/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2010 Pallets。
- 来源：[对应来源](https://pypi.org/project/MarkupSafe/3.0.3/)。版本依据及SHA见机器索引对应`frozen:MarkupSafe`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/MarkupSafe-3.0.3/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 357. numpy — 2.2.6

- 范围/位置：B；`2ByteASR.exe!PYZ:numpy`、`numpy/`。
- 许可：Copyright (c) 2005-2024, NumPy Developers. All rights reserved. Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met: * Redistributions of source code。组件版权声明：Copyright (c) 2005-2024, NumPy Developers.。
- 来源：[对应来源](https://pypi.org/project/numpy/2.2.6/)。版本依据及SHA见机器索引对应`frozen:numpy`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/numpy-2.2.6/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 358. oss2 — 2.19.1

- 范围/位置：B；`2ByteASR.exe!PYZ:oss2`、`oss2/`。
- 许可：未声明。组件版权声明：Copyright (c) 2015 aliyun.com。
- 来源：[对应来源](https://pypi.org/project/oss2/2.19.1/)。版本依据及SHA见机器索引对应`frozen:oss2`。
- 完整原文及现有材料：[LICENSE](materials/frozen/oss2-2.19.1/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 359. packaging — 26.2

- 范围/位置：B；`2ByteASR.exe!PYZ:packaging`、`packaging/`。
- 许可：Apache-2.0 OR BSD-2-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/packaging/26.2/)。版本依据及SHA见机器索引对应`frozen:packaging`。
- 完整原文及现有材料：[LICENSE](materials/frozen/packaging-26.2/LICENSE)；[LICENSE.APACHE](materials/frozen/packaging-26.2/LICENSE.APACHE)；[LICENSE.BSD](materials/frozen/packaging-26.2/LICENSE.BSD)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 360. pillow — 12.3.0

- 范围/位置：B；`2ByteASR.exe!PYZ:PIL`、`PIL/`。
- 许可：MIT-CMU。组件版权声明：Copyright © 1997-2011 by Secret Labs AB；Copyright © 1995-2011 by Fredrik Lundh and contributors；Copyright © 2010 by Jeffrey 'Alex' Clark and contributors；Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.。
- 来源：[对应来源](https://pypi.org/project/pillow/12.3.0/)。版本依据及SHA见机器索引对应`frozen:pillow`。
- 完整原文及现有材料：[LICENSE](materials/frozen/pillow-12.3.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 361. platformdirs — 4.11.0

- 范围/位置：B；`2ByteASR.exe!PYZ:platformdirs`、`platformdirs/`。
- 许可：MIT。组件版权声明：Copyright (c) 2010-202x The platformdirs developers。
- 来源：[对应来源](https://pypi.org/project/platformdirs/4.11.0/)。版本依据及SHA见机器索引对应`frozen:platformdirs`。
- 完整原文及现有材料：[LICENSE](materials/frozen/platformdirs-4.11.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 362. psutil — 7.2.2

- 范围/位置：B；`2ByteASR.exe!PYZ:psutil`、`psutil/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola。
- 来源：[对应来源](https://pypi.org/project/psutil/7.2.2/)。版本依据及SHA见机器索引对应`frozen:psutil`。
- 完整原文及现有材料：[LICENSE](materials/frozen/psutil-7.2.2/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 363. pycaw — 20251023

- 范围/位置：B；`2ByteASR.exe!PYZ:pycaw`、`pycaw/`。
- 许可：未声明。组件版权声明：Copyright (c) 2016 AndreMiras。
- 来源：[对应来源](https://pypi.org/project/pycaw/20251023/)。版本依据及SHA见机器索引对应`frozen:pycaw`。
- 完整原文及现有材料：[LICENSE](materials/frozen/pycaw-20251023/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 364. pycparser — 3.0

- 范围/位置：B；`2ByteASR.exe!PYZ:pycparser`、`pycparser/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2008-2022, Eli Bendersky。
- 来源：[对应来源](https://pypi.org/project/pycparser/3.0/)。版本依据及SHA见机器索引对应`frozen:pycparser`。
- 完整原文及现有材料：[LICENSE](materials/frozen/pycparser-3.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 365. pycryptodome — 3.23.0

- 范围/位置：B；`2ByteASR.exe!PYZ:Crypto`、`Crypto/`。
- 许可：BSD, Public Domain。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/pycryptodome/3.23.0/)。版本依据及SHA见机器索引对应`frozen:pycryptodome`。
- 完整原文及现有材料：[LICENSE.rst](materials/frozen/pycryptodome-3.23.0/LICENSE.rst)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 366. Pygments — 2.20.0

- 范围/位置：B；`2ByteASR.exe!PYZ:pygments`、`pygments/`。
- 许可：BSD-2-Clause。组件版权声明：Copyright (c) 2006-2022 by the respective authors (see AUTHORS file).。
- 来源：[对应来源](https://pypi.org/project/Pygments/2.20.0/)。版本依据及SHA见机器索引对应`frozen:Pygments`。
- 完整原文及现有材料：[LICENSE](materials/frozen/Pygments-2.20.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 367. pypinyin — 0.55.0

- 范围/位置：B；`2ByteASR.exe!PYZ:pypinyin`、`pypinyin/`。
- 许可：MIT。组件版权声明：Copyright (c) 2016 mozillazg, 闲耘 <hotoo.cn@gmail.com>。
- 来源：[对应来源](https://pypi.org/project/pypinyin/0.55.0/)。版本依据及SHA见机器索引对应`frozen:pypinyin`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/pypinyin-0.55.0/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 368. PySide6 — 6.9.2

- 范围/位置：B；`2ByteASR.exe!PYZ:PySide6`、`PySide6/`。
- 许可：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/PySide6/6.9.2/)。版本依据及SHA见机器索引对应`frozen:PySide6`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/frozen/PySide6-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 369. PySide6_Addons — 6.9.2

- 范围/位置：B；`2ByteASR.exe!PYZ:PySide6`、`PySide6/`。
- 许可：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/PySide6_Addons/6.9.2/)。版本依据及SHA见机器索引对应`frozen:PySide6_Addons`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/frozen/PySide6_Addons-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 370. PySide6_Essentials — 6.9.2

- 范围/位置：B；`2ByteASR.exe!PYZ:PySide6`、`PySide6/`。
- 许可：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/PySide6_Essentials/6.9.2/)。版本依据及SHA见机器索引对应`frozen:PySide6_Essentials`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/frozen/PySide6_Essentials-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 371. PyYAML — 6.0.3

- 范围/位置：B；`2ByteASR.exe!PYZ:yaml`、`yaml/`。
- 许可：MIT。组件版权声明：Copyright (c) 2017-2021 Ingy döt Net；Copyright (c) 2006-2016 Kirill Simonov。
- 来源：[对应来源](https://pypi.org/project/PyYAML/6.0.3/)。版本依据及SHA见机器索引对应`frozen:PyYAML`。
- 完整原文及现有材料：[LICENSE](materials/frozen/PyYAML-6.0.3/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 372. QtAwesome — 1.4.0

- 范围/位置：B；`2ByteASR.exe!PYZ:qtawesome`、`qtawesome/`。
- 许可：MIT。组件版权声明：Copyright (c) 2015 The Spyder development team。
- 来源：[对应来源](https://pypi.org/project/QtAwesome/1.4.0/)。版本依据及SHA见机器索引对应`frozen:QtAwesome`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/QtAwesome-1.4.0/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 373. QtPy — 2.4.3

- 范围/位置：B；`2ByteASR.exe!PYZ:qtpy`、`qtpy/`。
- 许可：MIT。组件版权声明：Copyright (c) 2011- QtPy contributors and others (see AUTHORS.md)。
- 来源：[对应来源](https://pypi.org/project/QtPy/2.4.3/)。版本依据及SHA见机器索引对应`frozen:QtPy`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/QtPy-2.4.3/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 374. referencing — 0.37.0

- 范围/位置：B；`2ByteASR.exe!PYZ:referencing`、`referencing/`。
- 许可：MIT。组件版权声明：Copyright (c) 2022 Julian Berman。
- 来源：[对应来源](https://pypi.org/project/referencing/0.37.0/)。版本依据及SHA见机器索引对应`frozen:referencing`。
- 完整原文及现有材料：[COPYING](materials/frozen/referencing-0.37.0/COPYING)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 375. requests — 2.33.0

- 范围/位置：B；`2ByteASR.exe!PYZ:requests`、`requests/`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/requests/2.33.0/)。版本依据及SHA见机器索引对应`frozen:requests`。
- 完整原文及现有材料：[LICENSE](materials/frozen/requests-2.33.0/LICENSE)；[NOTICE](materials/frozen/requests-2.33.0/NOTICE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 376. rpds-py — 0.30.0

- 范围/位置：B；`2ByteASR.exe!PYZ:rpds`、`rpds/`。
- 许可：MIT。组件版权声明：Copyright (c) 2023 Julian Berman。
- 来源：[对应来源](https://pypi.org/project/rpds-py/0.30.0/)。版本依据及SHA见机器索引对应`frozen:rpds-py`。
- 完整原文及现有材料：[LICENSE](materials/frozen/rpds-py-0.30.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 377. setuptools — 81.0.0

- 范围/位置：B；`2ByteASR.exe!PYZ:setuptools`、`setuptools/`。
- 许可：MIT。组件版权声明：Copyright (c) 2026 <copyright holders>；Copyright (c) 2025 <copyright holders>；Copyright (c) 2012 Erik Rose；Copyright (c) 2010-202x The platformdirs developers；Copyright (c) 2021 Taneli Hukkinen；Copyright (c) 2012 Daniel Holth <dholth@fastmail.fm> and contributors。
- 来源：[对应来源](https://pypi.org/project/setuptools/81.0.0/)。版本依据及SHA见机器索引对应`frozen:setuptools`。
- 完整原文及现有材料：[LICENSE](materials/frozen/setuptools-81.0.0/LICENSE)；[ade78d0498-LICENSE](materials/frozen/setuptools-81.0.0/ade78d0498-LICENSE)；[458502e12d-LICENSE](materials/frozen/setuptools-81.0.0/458502e12d-LICENSE)；[9755a18519-LICENSE](materials/frozen/setuptools-81.0.0/9755a18519-LICENSE)；[5a57cb4db8-LICENSE](materials/frozen/setuptools-81.0.0/5a57cb4db8-LICENSE)；[09f1c8c9e9-LICENSE](materials/frozen/setuptools-81.0.0/09f1c8c9e9-LICENSE)；[cad1ef5bd3-LICENSE](materials/frozen/setuptools-81.0.0/cad1ef5bd3-LICENSE)；[LICENSE.APACHE](materials/frozen/setuptools-81.0.0/LICENSE.APACHE)；[LICENSE.BSD](materials/frozen/setuptools-81.0.0/LICENSE.BSD)；[29e0fd62e9-LICENSE](materials/frozen/setuptools-81.0.0/29e0fd62e9-LICENSE)；[b80816b0d5-LICENSE](materials/frozen/setuptools-81.0.0/b80816b0d5-LICENSE)；[LICENSE.txt](materials/frozen/setuptools-81.0.0/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 378. shiboken6 — 6.9.2

- 范围/位置：B；`2ByteASR.exe!PYZ:shiboken6`、`shiboken6/`。
- 许可：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/shiboken6/6.9.2/)。版本依据及SHA见机器索引对应`frozen:shiboken6`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/frozen/shiboken6-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 379. six — 1.17.0

- 范围/位置：B；`2ByteASR.exe!PYZ:six`、`six/`。
- 许可：MIT。组件版权声明：Copyright (c) 2010-2024 Benjamin Peterson。
- 来源：[对应来源](https://pypi.org/project/six/1.17.0/)。版本依据及SHA见机器索引对应`frozen:six`。
- 完整原文及现有材料：[LICENSE](materials/frozen/six-1.17.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 380. SoundCard — 0.4.6

- 范围/位置：B；`2ByteASR.exe!PYZ:soundcard`、`soundcard/`。
- 许可：BSD 3-clause。组件版权声明：Copyright (c) 2016 Bastian Bechtold。
- 来源：[对应来源](https://pypi.org/project/SoundCard/0.4.6/)。版本依据及SHA见机器索引对应`frozen:SoundCard`。
- 完整原文及现有材料：[LICENSE](materials/frozen/SoundCard-0.4.6/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 381. threadpoolctl — 3.6.0

- 范围/位置：B；`2ByteASR.exe!PYZ:threadpoolctl`、`threadpoolctl/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright (c) 2019, threadpoolctl contributors。
- 来源：[对应来源](https://pypi.org/project/threadpoolctl/3.6.0/)。版本依据及SHA见机器索引对应`frozen:threadpoolctl`。
- 完整原文及现有材料：[LICENSE](materials/frozen/threadpoolctl-3.6.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 382. tomli — 2.4.1

- 范围/位置：B；`2ByteASR.exe!PYZ:tomli`、`tomli/`。
- 许可：MIT。组件版权声明：Copyright (c) 2021 Taneli Hukkinen。
- 来源：[对应来源](https://pypi.org/project/tomli/2.4.1/)。版本依据及SHA见机器索引对应`frozen:tomli`。
- 完整原文及现有材料：[LICENSE](materials/frozen/tomli-2.4.1/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 383. typing_extensions — 4.16.0

- 范围/位置：B；`2ByteASR.exe!PYZ:typing_extensions`、`typing_extensions/`。
- 许可：PSF-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/typing_extensions/4.16.0/)。版本依据及SHA见机器索引对应`frozen:typing_extensions`。
- 完整原文及现有材料：[LICENSE](materials/frozen/typing_extensions-4.16.0/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 384. urllib3 — 2.7.0

- 范围/位置：B；`2ByteASR.exe!PYZ:urllib3`、`urllib3/`。
- 许可：MIT。组件版权声明：Copyright (c) 2008-2020 Andrey Petrov and contributors.。
- 来源：[对应来源](https://pypi.org/project/urllib3/2.7.0/)。版本依据及SHA见机器索引对应`frozen:urllib3`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/urllib3-2.7.0/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 385. websockets — 16.1.1

- 范围/位置：B；`2ByteASR.exe!PYZ:websockets`、`websockets/`。
- 许可：BSD-3-Clause。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/websockets/16.1.1/)。版本依据及SHA见机器索引对应`frozen:websockets`。
- 完整原文及现有材料：[LICENSE](materials/frozen/websockets-16.1.1/LICENSE)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 386. Werkzeug — 3.1.8

- 范围/位置：B；`2ByteASR.exe!PYZ:werkzeug`、`werkzeug/`。
- 许可：BSD-3-Clause。组件版权声明：Copyright 2007 Pallets。
- 来源：[对应来源](https://pypi.org/project/Werkzeug/3.1.8/)。版本依据及SHA见机器索引对应`frozen:Werkzeug`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/Werkzeug-3.1.8/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 387. wheel — 0.45.1

- 范围/位置：B；`2ByteASR.exe!PYZ:wheel`、`wheel/`。
- 许可：未声明。组件版权声明：Copyright (c) 2012 Daniel Holth <dholth@fastmail.fm> and contributors。
- 来源：[对应来源](https://pypi.org/project/wheel/0.45.1/)。版本依据及SHA见机器索引对应`frozen:wheel`。
- 完整原文及现有材料：[LICENSE.txt](materials/frozen/wheel-0.45.1/LICENSE.txt)
- 用途/集成：PyInstaller PYZ模块/CPython扩展；本地DLL见native evidence；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确认实际模块与该版本来源的字节对应；元数据不可代替上游许可，原文路径已定位。

## 388. CPython — 3.10.11

- 范围/位置：B；`python310.dll`、`python3.dll`、`base_library.zip`。
- 许可：PSF-2.0 and bundled component licenses。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/python/cpython/v3.10.11/LICENSE)。版本依据及SHA见机器索引对应`runtime:python`。
- 完整原文及现有材料：[LICENSE.txt](materials/python/3.10.11/LICENSE.txt)
- 用途/集成：PyInstaller内嵌解释器/动态DLL；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：Python 3.10.11 LICENSE及完整第三方声明；OpenSSL/Tcl/Tk/zlib等实际版本通知。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未发现明确的独立CPython 3.10.11完整许可交付路径，后续补齐；拆分各本地传递库来源。

## 389. PyInstaller bootloader — 6.22.2

- 范围/位置：B,E；`2ByteASR.exe`。
- 许可：GPL-2.0-or-later with PyInstaller bootloader exception。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.2/COPYING.txt)。版本依据及SHA见机器索引对应`runtime:pyinstaller`。
- 完整原文及现有材料：[COPYING.txt](materials/pyinstaller/6.22.2/COPYING.txt)
- 用途/集成：构建工具E；bootloader代码嵌入EXE属B；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：COPYING及bootloader exception、对应来源。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对对应版本上游原文、传递依赖和再分发范围。

## 390. Qt6Core — 6.9.2

- 范围/位置：B；`PySide6/Qt6Core.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Core`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Core-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 391. Qt6DataVisualization — 6.9.2

- 范围/位置：B；`PySide6/Qt6DataVisualization.dll`。
- 许可：GPL-3.0-only OR commercial。组件版权声明：Copyright (C) 2016 The Qt Company Ltd.。
- 来源：[对应来源](https://raw.githubusercontent.com/qt/qtdatavis3d/v6.9.2/src/datavisualization/data/qbardataitem.h)。版本依据及SHA见机器索引对应`qt:Qt6DataVisualization`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6DataVisualization-6.9.2/LicenseRef-Qt-Commercial.txt)；[qbardataitem.h.txt](materials/qt/6.9.2/qbardataitem.h.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未见商业Qt授权凭据；GPL/LGPL全文、对应源码交付缺口；GPL模块不得按LGPL处理。

## 392. Qt6Gui — 6.9.2

- 范围/位置：B；`PySide6/Qt6Gui.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Gui`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Gui-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 393. Qt6Multimedia — 6.9.2

- 范围/位置：B；`PySide6/Qt6Multimedia.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Multimedia`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Multimedia-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 394. Qt6MultimediaWidgets — 6.9.2

- 范围/位置：B；`PySide6/Qt6MultimediaWidgets.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6MultimediaWidgets`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6MultimediaWidgets-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 395. Qt6Network — 6.9.2

- 范围/位置：B；`PySide6/Qt6Network.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Network`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Network-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 396. Qt6OpenGL — 6.9.2

- 范围/位置：B；`PySide6/Qt6OpenGL.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6OpenGL`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6OpenGL-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 397. Qt6OpenGLWidgets — 6.9.2

- 范围/位置：B；`PySide6/Qt6OpenGLWidgets.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6OpenGLWidgets`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6OpenGLWidgets-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 398. Qt6Pdf — 6.9.2

- 范围/位置：B；`PySide6/Qt6Pdf.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Pdf`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Pdf-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 399. Qt6Qml — 6.9.2

- 范围/位置：B；`PySide6/Qt6Qml.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Qml`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Qml-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 400. Qt6QmlMeta — 6.9.2

- 范围/位置：B；`PySide6/Qt6QmlMeta.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6QmlMeta`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6QmlMeta-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 401. Qt6QmlModels — 6.9.2

- 范围/位置：B；`PySide6/Qt6QmlModels.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6QmlModels`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6QmlModels-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 402. Qt6QmlWorkerScript — 6.9.2

- 范围/位置：B；`PySide6/Qt6QmlWorkerScript.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6QmlWorkerScript`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6QmlWorkerScript-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 403. Qt6Quick — 6.9.2

- 范围/位置：B；`PySide6/Qt6Quick.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Quick`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Quick-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 404. Qt6Svg — 6.9.2

- 范围/位置：B；`PySide6/Qt6Svg.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Svg`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Svg-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 405. Qt6Test — 6.9.2

- 范围/位置：B；`PySide6/Qt6Test.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Test`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Test-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 406. Qt6VirtualKeyboard — 6.9.2

- 范围/位置：B；`PySide6/Qt6VirtualKeyboard.dll`。
- 许可：GPL-3.0-only OR commercial。组件版权声明：Copyright (C) 2016 The Qt Company Ltd.。
- 来源：[对应来源](https://raw.githubusercontent.com/qt/qtvirtualkeyboard/v6.9.2/src/virtualkeyboard/qvirtualkeyboardinputcontext.h)。版本依据及SHA见机器索引对应`qt:Qt6VirtualKeyboard`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6VirtualKeyboard-6.9.2/LicenseRef-Qt-Commercial.txt)；[qvirtualkeyboardinputcontext.h.txt](materials/qt/6.9.2/qvirtualkeyboardinputcontext.h.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未见商业Qt授权凭据；GPL/LGPL全文、对应源码交付缺口；GPL模块不得按LGPL处理。

## 407. Qt6Widgets — 6.9.2

- 范围/位置：B；`PySide6/Qt6Widgets.dll`。
- 许可：LGPL/GPL/commercial；须按具体Qt模块及第三方代码拆分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qtforpython-6/licenses.html)。版本依据及SHA见机器索引对应`qt:Qt6Widgets`。
- 完整原文及现有材料：[LicenseRef-Qt-Commercial.txt](materials/qt/Qt6Widgets-6.9.2/LicenseRef-Qt-Commercial.txt)；[AFL-2.1.txt](materials/qt/6.9.2/qtbase/AFL-2.1.txt)；[Apache-2.0.txt](materials/qt/6.9.2/qtbase/Apache-2.0.txt)；[BSD-2-Clause.txt](materials/qt/6.9.2/qtbase/BSD-2-Clause.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/qtbase/BSD-3-Clause.txt)；[BSD-4-Clause.txt](materials/qt/6.9.2/qtbase/BSD-4-Clause.txt)；[BSL-1.0.txt](materials/qt/6.9.2/qtbase/BSL-1.0.txt)；[Bitstream-Vera.txt](materials/qt/6.9.2/qtbase/Bitstream-Vera.txt)；[CC0-1.0.txt](materials/qt/6.9.2/qtbase/CC0-1.0.txt)；[FTL.txt](materials/qt/6.9.2/qtbase/FTL.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/qtbase/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/qtbase/GPL-2.0-only.txt)；[GPL-2.0-or-later.txt](materials/qt/6.9.2/qtbase/GPL-2.0-or-later.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/qtbase/GPL-3.0-only.txt)；[HPND.txt](materials/qt/6.9.2/qtbase/HPND.txt)；[IJG.txt](materials/qt/6.9.2/qtbase/IJG.txt)；[IPL-1.0.txt](materials/qt/6.9.2/qtbase/IPL-1.0.txt)；[Imlib2.txt](materials/qt/6.9.2/qtbase/Imlib2.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/qtbase/LGPL-3.0-only.txt)；[Libpng.txt](materials/qt/6.9.2/qtbase/Libpng.txt)；[LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt](materials/qt/6.9.2/qtbase/LicenseRef-BSD-3-Clause-with-PCRE2-Binary-Like-Packages-Exception.txt)；[LicenseRef-ICC-License.txt](materials/qt/6.9.2/qtbase/LicenseRef-ICC-License.txt)；[LicenseRef-Lcs-Telegraphics.txt](materials/qt/6.9.2/qtbase/LicenseRef-Lcs-Telegraphics.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/qtbase/LicenseRef-Qt-Commercial.txt)；[LicenseRef-SHA1-Public-Domain.txt](materials/qt/6.9.2/qtbase/LicenseRef-SHA1-Public-Domain.txt)；[Linux-syscall-note.txt](materials/qt/6.9.2/qtbase/Linux-syscall-note.txt)；[MIT-Khronos-old.txt](materials/qt/6.9.2/qtbase/MIT-Khronos-old.txt)；[MIT-open-group.txt](materials/qt/6.9.2/qtbase/MIT-open-group.txt)；[MIT.txt](materials/qt/6.9.2/qtbase/MIT.txt)；[MPL-2.0.txt](materials/qt/6.9.2/qtbase/MPL-2.0.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/qtbase/Qt-GPL-exception-1.0.txt)；[SPL-1.0.txt](materials/qt/6.9.2/qtbase/SPL-1.0.txt)；[Unicode-3.0.txt](materials/qt/6.9.2/qtbase/Unicode-3.0.txt)；[X11.txt](materials/qt/6.9.2/qtbase/X11.txt)；[Xerox.txt](materials/qt/6.9.2/qtbase/Xerox.txt)；[Zlib.txt](materials/qt/6.9.2/qtbase/Zlib.txt)；[blessing.txt](materials/qt/6.9.2/qtbase/blessing.txt)；[libpng-2.0.txt](materials/qt/6.9.2/qtbase/libpng-2.0.txt)；[Apache-2.0.txt](materials/qt/6.9.2/pyside/Apache-2.0.txt)；[BSD-3-Clause.txt](materials/qt/6.9.2/pyside/BSD-3-Clause.txt)；[GFDL-1.3-no-invariants-only.txt](materials/qt/6.9.2/pyside/GFDL-1.3-no-invariants-only.txt)；[GPL-2.0-only.txt](materials/qt/6.9.2/pyside/GPL-2.0-only.txt)；[GPL-3.0-only.txt](materials/qt/6.9.2/pyside/GPL-3.0-only.txt)；[LGPL-3.0-only.txt](materials/qt/6.9.2/pyside/LGPL-3.0-only.txt)；[LicenseRef-Qt-Commercial.txt](materials/qt/6.9.2/pyside/LicenseRef-Qt-Commercial.txt)；[Qt-GPL-exception-1.0.txt](materials/qt/6.9.2/pyside/Qt-GPL-exception-1.0.txt)
- 用途/集成：动态DLL/PySide6绑定；VirtualKeyboard另有Qt输入法插件；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应6.9.2模块许可、Qt第三方声明、对应源码和补丁/构建资料；适用LGPL的替换及调试修改例外。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：模块第三方清单尚未逐项闭合；QtPdf包含PDFium等内容，不因没有QtWebEngine而消失。

## 408. FFmpeg / ffprobe (gyan essentials) — 9.0

- 范围/位置：B；`tools/ffmpeg/bin/ffmpeg.exe`、`tools/ffmpeg/bin/ffprobe.exe`。
- 许可：GPL-3.0-or-later (actual enabled build)。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://ffmpeg.org/legal.html)。版本依据及SHA见机器索引对应`media:ffmpeg-cli`。
- 完整原文及现有材料：[ffmpeg-GPLv3.txt](ffmpeg-GPLv3.txt)
- 用途/集成：独立CLI进程，文件/管道媒体接口；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：实际9.0构建及全部链接依赖的Corresponding Source、补丁、构建脚本；GNU GPL及版权。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：精确上游构建来源链、每个静态外部库版本及可实际取得的对应源码未闭合。

## 409. mpv — v0.41.0-923-g7b8915bc1

- 范围/位置：B；`tools/mpv/mpv.exe`、`tools/mpv/mpv.com`。
- 许可：GPL-2.0-or-later for mpv; linked libraries may impose additional/version3 terms。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/mpv-player/mpv/7b8915bc1d/Copyright)。版本依据及SHA见机器索引对应`media:mpv`。
- 完整原文及现有材料：[mpv-Copyright.txt](materials/media/mpv-v0.41.0-923-g7b8915bc1/mpv-Copyright.txt)
- 用途/集成：独立mpv.exe + Win32 HWND嵌入 + JSON命名管道/overlay，非Python libmpv绑定；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：精确mpv/FFmpeg/libplacebo/静态依赖对应源码、补丁与构建环境/脚本；实际适用GPL全文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未发现独立libmpv DLL/第三方Python-mpv绑定；不要因构建参数libmpv=true误报应用使用libmpv；完整对应源码和dirty来源未建立。

- test.4定点复核：载荷mpv.exe SHA256 `09dc5c35…a0243`、配对studio_mpv.py与封存PYZ一致；既有导出回执证实该EXE/--wid/JSON管道。已纠正REVIEW错误libmpv动态绑定推断；进程边界的GPL分析与内部对应源码仍独立开放。

## 410. PyAV linked FFmpeg / x264 / x265 — PyAV 17.1.0; FFmpeg 8.1.1; build 8.1.1-2

- 范围/位置：B；`av/`、`av.libs/`、`wheels/av-17.1.0-cp310-cp310-win_amd64.whl`。
- 许可：PyAV BSD-3-Clause; FFmpeg self-reports LGPL-3.0-or-later; x264 GPL-2.0-or-later unless additional rights。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/PyAV-Org/PyAV/v17.1.0/LICENSE.txt)；[对应来源](https://github.com/PyAV-Org/pyav-ffmpeg/blob/8.1.1-2/patches/ffmpeg.patch)；[对应来源](https://code.videolan.org/videolan/x264/-/blob/32c3b801191522961102d4bea292cdb61068d0dd/COPYING)。版本依据及SHA见机器索引对应`media:pyav-ffmpeg`。
- 完整原文及现有材料：[LICENSE.txt](materials/media/PyAV_linked_FFmpeg_x264_x265-PyAV_17.1.0_FFmpeg_8.1.1_build_8.1.1-2/LICENSE.txt)；[pyav-source.tar.gz](source-materials/pyav-17.1.0/pyav-source.tar.gz)；[pyav-ffmpeg-build-source.tar.gz](source-materials/pyav-17.1.0/pyav-ffmpeg-build-source.tar.gz)；[ffmpeg-source.tar.xz](source-materials/pyav-17.1.0/ffmpeg-source.tar.xz)；[COPYING.LGPLv2.1](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv2.1)；[COPYING.GPLv2](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv2)；[COPYING.LGPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.LGPLv3)；[COPYING.GPLv3](materials/pyav-codecs/ffmpeg-source/COPYING.GPLv3)；[x264-source.tar.bz2](source-materials/pyav-17.1.0/x264-source.tar.bz2)；[COPYING](materials/pyav-codecs/x264-source/COPYING)；[x265-source.tar.gz](source-materials/pyav-17.1.0/x265-source.tar.gz)；[COPYING](materials/pyav-codecs/x265-source/COPYING)
- 用途/集成：同进程CPython扩展→FFmpeg DLL→x264/x265 DLL，应用正常解码/帧/导出入口import av；修改/补丁：实际wheel匹配PyPI SHA256；25个av.libs文件与该wheel一致；上游构建有移除GPL检查的补丁。
- 源码与配套义务：核清x264/x265版本许可/额外商业授权；匹配版本对应源/上游补丁/构建脚本；完整库版权许可。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未见编码库额外授权；在来源授权闭合前不得按纯LGPL链批准；匹配LGPL构建或额外许可方案须先列出能力影响并验证，不直接换库或减编码能力；新增：pyav-ffmpeg README写x264 32c3b801，但pkg.py固定b35605ac；后者源码SHA已匹配上游脚本，DLL源码对应关系仍未闭合。x2654.2源码和原文已取得，不等于组合授权问题已解决。。

## 411. Qt Multimedia FFmpeg — avcodec 61.19.101 / avformat 61.7.100 / avutil 59.39.100

- 范围/位置：B；`PySide6/avcodec-61.dll`、`PySide6/avformat-61.dll`、`PySide6/avutil-59.dll`。
- 许可：LGPL-2.1-or-later (binary self-report)。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://doc.qt.io/qt-6.9/qtmultimedia-attribution-ffmpeg.html)。版本依据及SHA见机器索引对应`media:qt-ffmpeg`。
- 完整原文及现有材料：[lgpl-2.1.txt](materials/common/lgpl-2.1.txt)
- 用途/集成：QtMultimedia动态加载独立FFmpeg副本；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：该Qt实际FFmpeg二进制对应源码/Qt补丁与完整第三方声明。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：不能用gyan9.0或PyAV8.1.1源码替代；完整来源尚未闭合。

## 412. Remotion compositor FFmpeg — n7.1 / @remotion/compositor-win32-x64-msvc 4.0.513

- 范围/位置：B；`renderer/node_modules/@remotion/compositor-win32-x64-msvc/`、`avcodec-61.dll`、`avformat-61.dll`。
- 许可：GPL-2.0-or-later self-report; libfdk-aac interaction unresolved。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`media:remotion-ffmpeg`。
- 完整原文及现有材料：[gpl-2.0.txt](materials/common/gpl-2.0.txt)；[config.yml](source-materials/remotion-4.0.513/splitter/.circleci/config.yml)；[build.yml](source-materials/remotion-4.0.513/splitter/.github/workflows/build.yml)；[Cargo.lock](source-materials/remotion-4.0.513/splitter/Cargo.lock)；[Cargo.toml](source-materials/remotion-4.0.513/splitter/Cargo.toml)；[Dockerfile](source-materials/remotion-4.0.513/splitter/Dockerfile)；[Dockerfile-aws](source-materials/remotion-4.0.513/splitter/Dockerfile-aws)；[README.md](source-materials/remotion-4.0.513/splitter/README.md)；[aac.patch](source-materials/remotion-4.0.513/splitter/aac.patch)；[build.rs](source-materials/remotion-4.0.513/splitter/build.rs)；[clean.mjs](source-materials/remotion-4.0.513/splitter/clean.mjs)；[compile-av1.mjs](source-materials/remotion-4.0.513/splitter/compile-av1.mjs)；[compile-fdkaac.mjs](source-materials/remotion-4.0.513/splitter/compile-fdkaac.mjs)；[compile-ffmpeg.mjs](source-materials/remotion-4.0.513/splitter/compile-ffmpeg.mjs)；[compile-libmp3lame.mjs](source-materials/remotion-4.0.513/splitter/compile-libmp3lame.mjs)；[compile-nvenc.mjs](source-materials/remotion-4.0.513/splitter/compile-nvenc.mjs)；[compile-opus.mjs](source-materials/remotion-4.0.513/splitter/compile-opus.mjs)；[compile-vpx.mjs](source-materials/remotion-4.0.513/splitter/compile-vpx.mjs)；[compile-x264.mjs](source-materials/remotion-4.0.513/splitter/compile-x264.mjs)；[compile-x265.mjs](source-materials/remotion-4.0.513/splitter/compile-x265.mjs)；[compile-zimg.mjs](source-materials/remotion-4.0.513/splitter/compile-zimg.mjs)；[const.mjs](source-materials/remotion-4.0.513/splitter/const.mjs)；[fdk-aac-free.patch](source-materials/remotion-4.0.513/splitter/fdk-aac-free.patch)；[fix-links.mjs](source-materials/remotion-4.0.513/splitter/fix-links.mjs)；[fix-linux-links.mjs](source-materials/remotion-4.0.513/splitter/fix-linux-links.mjs)；[get-from-docker.mjs](source-materials/remotion-4.0.513/splitter/get-from-docker.mjs)；[hevc_ps.patch](source-materials/remotion-4.0.513/splitter/hevc_ps.patch)；[main.rs](source-materials/remotion-4.0.513/splitter/main.rs)；[x265-api.patch](source-materials/remotion-4.0.513/splitter/x265-api.patch)；[zip.mjs](source-materials/remotion-4.0.513/splitter/zip.mjs)；[sys-SOURCE.md](source-materials/remotion-4.0.513/sys-SOURCE.md)；[remotion-Cargo.lock](source-materials/remotion-4.0.513/remotion-Cargo.lock)；[remotion-Cargo.toml](source-materials/remotion-4.0.513/remotion-Cargo.toml)；[remotion-compositor-build.ts](source-materials/remotion-4.0.513/remotion-compositor-build.ts)；[remotion-ffmpeg-license.mdx](source-materials/remotion-4.0.513/remotion-ffmpeg-license.mdx)；[ffmpeg-7.1.tar.xz](source-materials/remotion-4.0.513/ffmpeg-7.1.tar.xz)；[x265-419182243-source.tar.gz](source-materials/remotion-4.0.513/x265-419182243-source.tar.gz)；[x265-419182243-COPYING.txt](source-materials/remotion-4.0.513/x265-419182243-COPYING.txt)；[x264-source.tar.bz2](source-materials/pyav-17.1.0/x264-source.tar.bz2)
- 用途/集成：Remotion子进程/原生compositor动态链接；部分DLL又被复制到冻结根目录；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：特定n7.1构建完整对应源码/补丁与所有编码库授权证明。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未建立此精确FFmpeg构建的源码/授权链；不据配置字符串独断整个包nonfree，也不予放行；compositor实际avcodec内嵌x264 r3222 b35605a、x265 3.4+28-419182243；对应基础源码已补，Windows预编译库构建参数/补丁与fdk-aac-free原文尚未闭合；不能与PyAV的x264矛盾混写。。

- 构建资料许可纠正：39ddfbb树无LICENSE/整体GPL声明；不能套Remotion主仓库许可。原样20件从明确GPL-2.0-or-later的50b6a0c0提供于[splitter-licensed/](source-materials/remotion-4.0.513/splitter-licensed/NOTICE.md)，每件blob同39；9件不同旧文件未获此授权。脚本/补丁许可与产出FDK混合二进制许可分开；Rust/Cargo源缺失已补，不再列缺，仅相容授权/实际静态输入开放。

## 413. Node.js — 24.13.0

- 范围/位置：B；`tools/node/node.exe`。
- 许可：MIT plus bundled notices。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/nodejs/node/v24.13.0/LICENSE)。版本依据及SHA见机器索引对应`runtime:node`。
- 完整原文及现有材料：[node-LICENSE.txt](materials/runtime/Node.js-24.13.0/node-LICENSE.txt)
- 用途/集成：应用自带Node运行renderer子进程；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未重建二进制；保留版本来源记录。

## 414. Chrome Headless Shell — 149.0.7790.0

- 范围/位置：B；`renderer/node_modules/.remotion/chrome-headless-shell/`。
- 许可：Chromium BSD and numerous bundled third-party licenses。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`runtime:chromium`。
- 完整原文及现有材料：[LICENSE.headless_shell](materials/runtime/Chrome_Headless_Shell-149.0.7790.0/LICENSE.headless_shell)
- 用途/集成：Remotion自带headless Chromium独立渲染进程；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：该2MB原文确实随包，但未逐项拆分Chrome全部传递组件及对应源码/构建revision；不能把它等同系统Chrome。

## 415. MOSS-Transcribe-Diarize — eda4b9f13f1574765a80438c9797780a9bd48112

- 范围/位置：B；`third_party/MOSS-Transcribe-Diarize`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://github.com/OpenMOSS/MOSS-Transcribe-Diarize.git)；[对应来源](https://raw.githubusercontent.com/OpenMOSS/MOSS-Transcribe-Diarize/eda4b9f13f1574765a80438c9797780a9bd48112/LICENSE)。版本依据及SHA见机器索引对应`source:moss`。
- 完整原文及现有材料：[LICENSE](materials/source/MOSS-Transcribe-Diarize-eda4b9f13f1574765a80438c9797780a9bd48112/LICENSE)
- 用途/集成：源码随包供私有模型Python运行；修改/补丁：本地仓库HEAD匹配锁定revision且status为空；包内子集匹配构建快照。
- 源码与配套义务：Apache-2.0正文、上游版权和NOTICE（如有）；修改文件显著变更说明；保存本地补丁。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：如公开源码包把忽略的third_party目录纳入，也归A；当前Git不跟踪该目录。

## 416. FireRedASR2S — 4e7d9aaf4482a47cec1724807026b9b151926eb5

- 范围/位置：B；`third_party/FireRedASR2S`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://github.com/FireRedTeam/FireRedASR2S.git)；[对应来源](https://raw.githubusercontent.com/FireRedTeam/FireRedASR2S/4e7d9aaf4482a47cec1724807026b9b151926eb5/LICENSE)。版本依据及SHA见机器索引对应`source:firered`。
- 完整原文及现有材料：[LICENSE](materials/source/FireRedASR2S-4e7d9aaf4482a47cec1724807026b9b151926eb5/LICENSE)；[firered-local.patch](source-materials/build-records/firered-local.patch)；[firered-current-with-notices.patch](source-materials/build-records/firered-current-with-notices.patch)
- 用途/集成：源码随包供私有模型Python运行；修改/补丁：5处实质修改、49处仅换行变化、6文件精确匹配；53上游文件未分发。
- 源码与配套义务：Apache-2.0正文、上游版权和NOTICE（如有）；修改文件显著变更说明；保存本地补丁。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：已核实；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：FireRed五处修改需明确标识；不能只写未修改或只链接主分支。

## 417. OpenMOSS-Team/MOSS-Transcribe-Diarize — e6d68cdfcddbdad1a7e8454f0cb859cad76e2502

- 范围/位置：C；`models/MOSS-Transcribe-Diarize`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/OpenMOSS-Team/MOSS-Transcribe-Diarize/tree/e6d68cdfcddbdad1a7e8454f0cb859cad76e2502)。版本依据及SHA见机器索引对应`model:moss`。
- 完整原文及现有材料：[model-moss-README_md.txt](materials/models/moss/model-moss-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 418. FireRedTeam/FireRedVAD — 7990aaccc6b7aec1e527743bd30201f2c4a03b8c

- 范围/位置：C；`models/FireRedVAD`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/FireRedTeam/FireRedVAD/tree/7990aaccc6b7aec1e527743bd30201f2c4a03b8c)。版本依据及SHA见机器索引对应`model:firered_vad`。
- 完整原文及现有材料：[model-firered_vad-README_md.txt](materials/models/firered_vad/model-firered_vad-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 419. FireRedTeam/FireRedASR2-AED — 2304afed56eacfee6256dee5937ed22ffa0b64ec

- 范围/位置：C；`models/FireRedASR2-AED`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/FireRedTeam/FireRedASR2-AED/tree/2304afed56eacfee6256dee5937ed22ffa0b64ec)。版本依据及SHA见机器索引对应`model:firered_aed`。
- 完整原文及现有材料：[model-firered_aed-README_md.txt](materials/models/firered_aed/model-firered_aed-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 420. Qwen/Qwen3-ASR-1.7B — 7278e1e70fe206f11671096ffdd38061171dd6e5

- 范围/位置：C；`models/Qwen3-ASR-1.7B`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/Qwen/Qwen3-ASR-1.7B/tree/7278e1e70fe206f11671096ffdd38061171dd6e5)。版本依据及SHA见机器索引对应`model:qwen_asr`。
- 完整原文及现有材料：[model-qwen_asr-README_md.txt](materials/models/qwen_asr/model-qwen_asr-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 421. Qwen/Qwen3-ForcedAligner-0.6B — c7cbfc2048c462b0d63a45797104fc9db3ad62b7

- 范围/位置：C；`models/Qwen3-ForcedAligner-0.6B`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B/tree/c7cbfc2048c462b0d63a45797104fc9db3ad62b7)。版本依据及SHA见机器索引对应`model:qwen_aligner`。
- 完整原文及现有材料：[model-qwen_aligner-README_md.txt](materials/models/qwen_aligner/model-qwen_aligner-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 422. openai/whisper-large-v3-turbo — 41f01f3fe87f28c78e2fbf8b568835947dd65ed9

- 范围/位置：C；`models/Whisper-large-v3-turbo`。
- 许可：mit。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/openai/whisper-large-v3-turbo/tree/41f01f3fe87f28c78e2fbf8b568835947dd65ed9)。版本依据及SHA见机器索引对应`model:whisper_turbo`。
- 完整原文及现有材料：[model-whisper_turbo-README_md.txt](materials/models/whisper_turbo/model-whisper_turbo-README_md.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 423. FunAudioLLM/SenseVoiceSmall — 3847d57b6bdf2dd8875cb1508d2af43d80a16bf7

- 范围/位置：C；`models/SenseVoiceSmall`。
- 许可：FunASR Model Open Source License Agreement v1.1 (linked mutable text)。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/tree/3847d57b6bdf2dd8875cb1508d2af43d80a16bf7)。版本依据及SHA见机器索引对应`model:sensevoice`。
- 完整原文及现有材料：[FunASR-MODEL_LICENSE-58830eca.txt](materials/models/sensevoice/FunASR-MODEL_LICENSE-58830eca.txt)；[model-sensevoice-README_md.txt](materials/models/sensevoice/model-sensevoice-README_md.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明；现已固定下载FunASR条款提交58830eca4012644aac0c3218c3ccc7d98f003fda；该提交仅固定本轮观察到的被链接条款，模型历史适用关系及单方更新条件仍须核实。。

## 424. funasr/paraformer-zh — d7811ee3ac581fbcfdeb37c98c6ba674028433dc

- 范围/位置：C；`models/Paraformer-zh`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/funasr/paraformer-zh/tree/d7811ee3ac581fbcfdeb37c98c6ba674028433dc)。版本依据及SHA见机器索引对应`model:paraformer`。
- 完整原文及现有材料：[model-paraformer-README_md.txt](materials/models/paraformer/model-paraformer-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 425. FunAudioLLM/Fun-ASR-Nano-2512 — 272c57b82523ada6fd87095e955f8e29100979ab

- 范围/位置：C；`models/Fun-ASR-Nano-2512`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512/tree/272c57b82523ada6fd87095e955f8e29100979ab)。版本依据及SHA见机器索引对应`model:funasr_nano`。
- 完整原文及现有材料：[model-funasr_nano-README_md.txt](materials/models/funasr_nano/model-funasr_nano-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：锁字段FunAudioLLM Research License与固定revision模型卡Apache-2.0不一致；按权重/配置/基础Qwen资源逐项纠正；required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 426. FireRedTeam/FireRedASR2-LLM — 2c5e0f415b9afb8f67cb8b00ea4c54959f70e824

- 范围/位置：C；`models/FireRedASR2-LLM`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/FireRedTeam/FireRedASR2-LLM/tree/2c5e0f415b9afb8f67cb8b00ea4c54959f70e824)。版本依据及SHA见机器索引对应`model:firered_llm`。
- 完整原文及现有材料：[model-firered_llm-README_md.txt](materials/models/firered_llm/model-firered_llm-README_md.txt)；[firered_llm-Qwen2-7B-Instruct_LICENSE](materials/models/firered_llm/firered_llm-Qwen2-7B-Instruct_LICENSE)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：包含Qwen2-7B-Instruct；子目录LICENSE已取得，但下载required_files未列入它；required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 427. zai-org/GLM-ASR-Nano-2512 — 61ba4e0b3309b6656edea3e93e419f7bd5c61957

- 范围/位置：C；`models/GLM-ASR-Nano-2512`。
- 许可：mit。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/zai-org/GLM-ASR-Nano-2512/tree/61ba4e0b3309b6656edea3e93e419f7bd5c61957)。版本依据及SHA见机器索引对应`model:glm_asr_nano`。
- 完整原文及现有材料：[model-glm_asr_nano-README_md.txt](materials/models/glm_asr_nano/model-glm_asr_nano-README_md.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 428. nvidia/canary-qwen-2.5b — b1469e1bba1cfe140205529c79c434ca47180960

- 范围/位置：C；`models/canary-qwen-2.5b`。
- 许可：cc-by-4.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/nvidia/canary-qwen-2.5b/tree/b1469e1bba1cfe140205529c79c434ca47180960)。版本依据及SHA见机器索引对应`model:canary_qwen`。
- 完整原文及现有材料：[model-canary_qwen-README_md.txt](materials/models/canary_qwen/model-canary_qwen-README_md.txt)；[canary_qwen-LICENSES](materials/models/canary_qwen/canary_qwen-LICENSES)；[ccby-4.0.txt](materials/common/ccby-4.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件；CC-BY-4.0署名、许可链接和修改说明；模型中的LICENSES已获取。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 429. facebook/omniASR-LLM-7B — 4b0bada258b398cb7e6c5b3a6ed5448fb914385b

- 范围/位置：C；`models/omniASR-LLM-7B`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/facebook/omniASR-LLM-7B/tree/4b0bada258b398cb7e6c5b3a6ed5448fb914385b)。版本依据及SHA见机器索引对应`model:omni_asr_llm_7b`。
- 完整原文及现有材料：[model-omni_asr_llm_7b-README_md.txt](materials/models/omni_asr_llm_7b/model-omni_asr_llm_7b-README_md.txt)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 430. speechbrain/spkrec-ecapa-voxceleb — 0f99f2d0ebe89ac095bcc5903c4dd8f72b367286

- 范围/位置：C；`models/spkrec-ecapa-voxceleb`。
- 许可："apache-2.0"。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/tree/0f99f2d0ebe89ac095bcc5903c4dd8f72b367286)。版本依据及SHA见机器索引对应`model:speaker_embedding`。
- 完整原文及现有材料：[model-speaker_embedding-README_md.txt](materials/models/speaker_embedding/model-speaker_embedding-README_md.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 431. nvidia/Nemotron-3-Diarization — f667ed73aee57d40cc39428eb768b4fd87a0a29e

- 范围/位置：C；`models/Nemotron-3-Diarization`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/nvidia/Nemotron-3-Diarization/tree/f667ed73aee57d40cc39428eb768b4fd87a0a29e)；[对应来源](https://openmdw.ai/license/1-1/)。版本依据及SHA见机器索引对应`model:nemotron`。
- 完整原文及现有材料：[nemotron-README.md](materials/models/nemotron/nemotron-README.md)；[openmdw.txt](materials/models/nemotron/openmdw.txt)；[OpenMDW-1.1.txt](materials/models/nemotron/OpenMDW-1.1.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 432. Qwen/Qwen3-1.7B — 70d244cc86ccca08cf5af4e1e306ecf908b1ad5e

- 范围/位置：C；`models/Canary-Qwen3-Tokenizer`。
- 许可：apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://huggingface.co/Qwen/Qwen3-1.7B/tree/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e)。版本依据及SHA见机器索引对应`model:canary_qwen_tokenizer`。
- 完整原文及现有材料：[model-canary_qwen_tokenizer-LICENSE.txt](materials/models/canary_qwen_tokenizer/model-canary_qwen_tokenizer-LICENSE.txt)；[model-canary_qwen_tokenizer-README_md.txt](materials/models/canary_qwen_tokenizer/model-canary_qwen_tokenizer-README_md.txt)；[canary_qwen_tokenizer-LICENSE](materials/models/canary_qwen_tokenizer/canary_qwen_tokenizer-LICENSE)；[apache-2.0.txt](materials/common/apache-2.0.txt)
- 用途/集成：模型工坊→download_models.ps1/模型完整性校验→私有Python worker；配置/词表/权重与远程代码需分别审查；修改/补丁：包内没有该模型权重；下载时按文件哈希校验。未修改模型的声明仅限无本轮修改，不代替模型衍生关系证明。
- 源码与配套义务：精确revision模型卡、许可全文、版权/NOTICE、基础模型/词表条款；向用户提供来源及适用条件。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：锁文件缺license字段；对应revision LICENSE已取得Apache-2.0；required_files只含运行文件，许可/模型卡通常未下载；在下载回执/材料包记录每项来源；部分模型卡引用可变main许可，需固定版本原文；不得以通用开源字样作为证明。

## 433. nemo_toolkit[asr] — 3.0.0

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.nemo_toolkit[asr]`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/nemo_toolkit/3.0.0/)。版本依据及SHA见机器索引对应`download:canary:nemo_toolkit[asr]`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 434. peft — 0.18.0

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.peft`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/peft/0.18.0/)。版本依据及SHA见机器索引对应`download:canary:peft`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 435. sacrebleu — 2.5.1

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.sacrebleu`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/sacrebleu/2.5.1/)。版本依据及SHA见机器索引对应`download:canary:sacrebleu`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 436. seaborn — 0.13.2

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.seaborn`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/seaborn/0.13.2/)。版本依据及SHA见机器索引对应`download:canary:seaborn`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 437. transformers — 4.57.1

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/4.57.1/)。版本依据及SHA见机器索引对应`download:canary:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 438. huggingface_hub — 0.36.2

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/0.36.2/)。版本依据及SHA见机器索引对应`download:canary:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 439. tokenizers — 0.22.2

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)。版本依据及SHA见机器索引对应`download:canary:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 440. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:canary:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 441. librosa — 0.11.0

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.librosa`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/librosa/0.11.0/)。版本依据及SHA见机器索引对应`download:canary:librosa`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 442. soundfile — 0.14.0

- 范围/位置：C；`dependencies.lock.json#environments.canary.packages.soundfile`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.14.0/)。版本依据及SHA见机器索引对应`download:canary:soundfile`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 443. transformers — 5.14.1

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/5.14.1/)。版本依据及SHA见机器索引对应`download:glm_asr:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 444. huggingface_hub — 1.24.0

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/1.24.0/)。版本依据及SHA见机器索引对应`download:glm_asr:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 445. tokenizers — 0.22.2

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)。版本依据及SHA见机器索引对应`download:glm_asr:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 446. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:glm_asr:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 447. librosa — 0.11.0

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.librosa`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/librosa/0.11.0/)。版本依据及SHA见机器索引对应`download:glm_asr:librosa`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 448. soundfile — 0.14.0

- 范围/位置：C；`dependencies.lock.json#environments.glm_asr.packages.soundfile`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.14.0/)。版本依据及SHA见机器索引对应`download:glm_asr:soundfile`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 449. psutil — 7.2.2

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.psutil`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/psutil/7.2.2/)。版本依据及SHA见机器索引对应`download:main:psutil`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 450. transformers — 4.57.6

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/4.57.6/)。版本依据及SHA见机器索引对应`download:main:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 451. huggingface_hub — 0.36.2

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/0.36.2/)。版本依据及SHA见机器索引对应`download:main:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 452. tokenizers — 0.22.2

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)。版本依据及SHA见机器索引对应`download:main:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 453. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:main:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 454. soundfile — 0.14.0

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.soundfile`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.14.0/)。版本依据及SHA见机器索引对应`download:main:soundfile`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 455. kaldiio — 2.18.1

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.kaldiio`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldiio/2.18.1/)。版本依据及SHA见机器索引对应`download:main:kaldiio`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 456. kaldi_native_fbank — 1.22.3

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.kaldi_native_fbank`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldi_native_fbank/1.22.3/)。版本依据及SHA见机器索引对应`download:main:kaldi_native_fbank`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 457. textgrid — 1.6.1

- 范围/位置：C；`dependencies.lock.json#environments.main.packages.textgrid`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/textgrid/1.6.1/)。版本依据及SHA见机器索引对应`download:main:textgrid`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 458. transformers — 5.14.1

- 范围/位置：C；`dependencies.lock.json#environments.moss.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/5.14.1/)。版本依据及SHA见机器索引对应`download:moss:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 459. huggingface_hub — 1.24.0

- 范围/位置：C；`dependencies.lock.json#environments.moss.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/1.24.0/)。版本依据及SHA见机器索引对应`download:moss:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 460. tokenizers — 0.22.2

- 范围/位置：C；`dependencies.lock.json#environments.moss.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)。版本依据及SHA见机器索引对应`download:moss:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 461. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.moss.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:moss:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 462. transformers — 4.57.6

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/transformers/4.57.6/)。版本依据及SHA见机器索引对应`download:firered_llm:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 463. huggingface_hub — 0.36.2

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/0.36.2/)。版本依据及SHA见机器索引对应`download:firered_llm:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 464. tokenizers — 0.22.2

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.22.2/)。版本依据及SHA见机器索引对应`download:firered_llm:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 465. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:firered_llm:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 466. accelerate — 1.12.0

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.accelerate`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/accelerate/1.12.0/)。版本依据及SHA见机器索引对应`download:firered_llm:accelerate`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 467. peft — 0.18.0

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.peft`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/peft/0.18.0/)。版本依据及SHA见机器索引对应`download:firered_llm:peft`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 468. kaldiio — 2.18.1

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.kaldiio`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldiio/2.18.1/)。版本依据及SHA见机器索引对应`download:firered_llm:kaldiio`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 469. kaldi_native_fbank — 1.22.3

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.kaldi_native_fbank`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/kaldi_native_fbank/1.22.3/)。版本依据及SHA见机器索引对应`download:firered_llm:kaldi_native_fbank`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 470. numpy — 2.2.6

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.numpy`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/numpy/2.2.6/)。版本依据及SHA见机器索引对应`download:firered_llm:numpy`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 471. sentencepiece — 0.2.2

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.sentencepiece`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/sentencepiece/0.2.2/)。版本依据及SHA见机器索引对应`download:firered_llm:sentencepiece`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 472. soundfile — 0.14.0

- 范围/位置：C；`dependencies.lock.json#environments.firered_llm.packages.soundfile`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.14.0/)。版本依据及SHA见机器索引对应`download:firered_llm:soundfile`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 473. transformers — 5.18.0.dev0

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.transformers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://github.com/huggingface/transformers/archive/4b28d51d0d5f17ec20c23a187d0475a8e68810c8.zip)。版本依据及SHA见机器索引对应`download:nemotron:transformers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 474. huggingface_hub — 1.32.0

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.huggingface_hub`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/huggingface_hub/1.32.0/)。版本依据及SHA见机器索引对应`download:nemotron:huggingface_hub`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 475. tokenizers — 0.23.1

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.tokenizers`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/tokenizers/0.23.1/)。版本依据及SHA见机器索引对应`download:nemotron:tokenizers`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 476. safetensors — 0.8.0

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.safetensors`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/safetensors/0.8.0/)。版本依据及SHA见机器索引对应`download:nemotron:safetensors`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 477. librosa — 0.11.0

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.librosa`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/librosa/0.11.0/)。版本依据及SHA见机器索引对应`download:nemotron:librosa`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 478. numpy — 2.2.6

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.numpy`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/numpy/2.2.6/)。版本依据及SHA见机器索引对应`download:nemotron:numpy`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 479. soundfile — 0.13.1

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.soundfile`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/soundfile/0.13.1/)。版本依据及SHA见机器索引对应`download:nemotron:soundfile`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 480. requests — 2.32.5

- 范围/位置：C；`dependencies.lock.json#environments.nemotron.packages.requests`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://pypi.org/project/requests/2.32.5/)。版本依据及SHA见机器索引对应`download:nemotron:requests`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：uv安装到按role分隔的私有venv；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：此为直接版本约束，传递依赖未全锁；实际运行下载清单须由本机独立receipt补足，不能用开发机freeze冒充。

## 481. PyTorch/Torchaudio CUDA wheels — 2.11.0+cu126 or 2.11.0+cu128

- 范围/位置：C；`scripts/install_managed_backend.py`、`dependencies.lock.json#runtime`。
- 许可：PyTorch BSD-style + NVIDIA CUDA component terms。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/LICENSE)；[对应来源](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html)。版本依据及SHA见机器索引对应`download:torch-cuda`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：根据设备选择官方PyTorch索引；不是当前Setup内CUDA运行库；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：实际下载wheel内BSD/NOTICE/NVIDIA组件EULA与再分发清单；版本化下载回执。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：CUDA组件/cuDNN/NCCL等实际Windows wheel内容与再分发版本未逐一取得，不能由cu128标签推导全部SDK许可。

## 482. uv — 0.11.7

- 范围/位置：C；`scripts/setup_managed_backend.ps1`、`scripts/install_managed_backend.py`。
- 许可：Apache-2.0 OR MIT。组件版权声明：Copyright (c) 2025 Astral Software Inc.。
- 来源：[对应来源](https://github.com/astral-sh/uv/releases/tag/0.11.7)。版本依据及SHA见机器索引对应`download:uv`。
- 完整原文及现有材料：[LICENSE-MIT](materials/uv/0.11.7/LICENSE-MIT)；[LICENSE-APACHE](materials/uv/0.11.7/LICENSE-APACHE)
- 用途/集成：首次模型准备下载，不改系统Python；当前B不含uv.exe安装器；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：保存精确下载release/asset SHA与随附第三方材料；不能只依据Python版本号。

## 483. managed CPython — 3.10.19 / 3.12.13

- 范围/位置：C；`scripts/setup_managed_backend.ps1`、`scripts/install_managed_backend.py`。
- 许可：PSF and Python-build-standalone component licenses。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://github.com/astral-sh/python-build-standalone)。版本依据及SHA见机器索引对应`download:managed CPython`。
- 完整原文及现有材料：[LICENSE.txt](materials/python/3.10.19/LICENSE.txt)；[LICENSE.txt](materials/python/3.12.13/LICENSE.txt)
- 用途/集成：首次模型准备下载，不改系统Python；当前B不含uv.exe安装器；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：保存精确下载release/asset SHA与随附第三方材料；不能只依据Python版本号。

## 484. FunASR — 1.4.1

- 范围/位置：C；`scripts/install_managed_backend.py:91`。
- 许可：MIT for code; models separately licensed。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://github.com/modelscope/FunASR)。版本依据及SHA见机器索引对应`download:funasr`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：pip安装代码；模型工坊另取权重；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：获取该版本代码原文和全部传递依赖；不要把代码MIT套给SenseVoice权重。

## 485. api-ms-win-core-console-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-console-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-console-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 486. api-ms-win-core-datetime-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-datetime-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-datetime-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 487. api-ms-win-core-debug-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-debug-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-debug-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 488. api-ms-win-core-errorhandling-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-errorhandling-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-errorhandling-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 489. api-ms-win-core-fibers-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-fibers-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-fibers-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 490. api-ms-win-core-fibers-l1-1-1.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-fibers-l1-1-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-fibers-l1-1-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 491. api-ms-win-core-file-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-file-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-file-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 492. api-ms-win-core-file-l1-2-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-file-l1-2-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-file-l1-2-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 493. api-ms-win-core-file-l2-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-file-l2-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-file-l2-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 494. api-ms-win-core-handle-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-handle-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-handle-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 495. api-ms-win-core-heap-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-heap-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-heap-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 496. api-ms-win-core-interlocked-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-interlocked-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-interlocked-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 497. api-ms-win-core-kernel32-legacy-l1-1-1.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-kernel32-legacy-l1-1-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-kernel32-legacy-l1-1-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 498. api-ms-win-core-libraryloader-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-libraryloader-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-libraryloader-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 499. api-ms-win-core-localization-l1-2-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-localization-l1-2-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-localization-l1-2-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 500. api-ms-win-core-memory-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-memory-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-memory-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 501. api-ms-win-core-namedpipe-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-namedpipe-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-namedpipe-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 502. api-ms-win-core-processenvironment-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-processenvironment-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-processenvironment-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 503. api-ms-win-core-processthreads-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-processthreads-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-processthreads-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 504. api-ms-win-core-processthreads-l1-1-1.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-processthreads-l1-1-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-processthreads-l1-1-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 505. api-ms-win-core-profile-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-profile-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-profile-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 506. api-ms-win-core-rtlsupport-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-rtlsupport-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-rtlsupport-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 507. api-ms-win-core-string-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-string-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-string-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 508. api-ms-win-core-synch-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-synch-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-synch-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 509. api-ms-win-core-synch-l1-2-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-synch-l1-2-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-synch-l1-2-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 510. api-ms-win-core-sysinfo-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-sysinfo-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-sysinfo-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 511. api-ms-win-core-sysinfo-l1-2-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-sysinfo-l1-2-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-sysinfo-l1-2-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 512. api-ms-win-core-timezone-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-timezone-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-timezone-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 513. api-ms-win-core-util-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-core-util-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-core-util-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 514. api-ms-win-crt-conio-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-conio-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-conio-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 515. api-ms-win-crt-convert-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-convert-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-convert-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 516. api-ms-win-crt-environment-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-environment-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-environment-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 517. api-ms-win-crt-filesystem-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-filesystem-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-filesystem-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 518. api-ms-win-crt-heap-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-heap-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-heap-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 519. api-ms-win-crt-locale-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-locale-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-locale-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 520. api-ms-win-crt-math-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-math-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-math-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 521. api-ms-win-crt-multibyte-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-multibyte-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-multibyte-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 522. api-ms-win-crt-private-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-private-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-private-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 523. api-ms-win-crt-process-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-process-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-process-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 524. api-ms-win-crt-runtime-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-runtime-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-runtime-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 525. api-ms-win-crt-stdio-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-stdio-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-stdio-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 526. api-ms-win-crt-string-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-string-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-string-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 527. api-ms-win-crt-time-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-time-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-time-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 528. api-ms-win-crt-utility-l1-1-0.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`api-ms-win-crt-utility-l1-1-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:api-ms-win-crt-utility-l1-1-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 529. libcrypto-1_1.dll — 1.1.1t

- 范围/位置：B；`libcrypto-1_1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libcrypto-1_1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 530. libcrypto-3-x64.dll — 3.6.4

- 范围/位置：B；`libcrypto-3-x64.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libcrypto-3-x64.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 531. libffi-7.dll — 准确版本未查明

- 范围/位置：B；`libffi-7.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libffi-7.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 532. libgcc_s_seh-1.dll — 准确版本未查明

- 范围/位置：B；`libgcc_s_seh-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libgcc_s_seh-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 533. libssl-1_1.dll — 1.1.1t

- 范围/位置：B；`libssl-1_1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libssl-1_1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 534. libssl-3-x64.dll — 3.6.4

- 范围/位置：B；`libssl-3-x64.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libssl-3-x64.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 535. libssp-0.dll — 准确版本未查明

- 范围/位置：B；`libssp-0.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libssp-0.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 536. libstdc++-6.dll — 准确版本未查明

- 范围/位置：B；`libstdc++-6.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libstdc++-6.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 537. libvpx-1.dll — 准确版本未查明

- 范围/位置：B；`libvpx-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libvpx-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 538. libwinpthread-1.dll — 1, 0, 0, 0

- 范围/位置：B；`libwinpthread-1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:libwinpthread-1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 539. MSVCR100.dll — 10.00.40219.473

- 范围/位置：B；`MSVCR100.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:MSVCR100.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 540. tcl86t.dll — 8.6.12

- 范围/位置：B；`tcl86t.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:tcl86t.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 541. tk86t.dll — 8.6.12

- 范围/位置：B；`tk86t.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:tk86t.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 542. ucrtbase.dll — 10.0.26100.4654 (WinBuild.160101.0800)

- 范围/位置：B；`ucrtbase.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:ucrtbase.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 543. VCRUNTIME140_1.dll — 14.29.30139.0 built by: vcwrkspc

- 范围/位置：B；`VCRUNTIME140_1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:VCRUNTIME140_1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 544. VCRUNTIME140.dll — 14.29.30139.0 built by: vcwrkspc

- 范围/位置：B；`VCRUNTIME140.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:VCRUNTIME140.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 545. zlib1.dll — 2.2.11

- 范围/位置：B；`zlib1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:zlib1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 546. avcodec-62-0f4d449c1bbaaa5eeb9f8a10b4cc7e85.dll — 62.28.101

- 范围/位置：B；`av.libs/avcodec-62-0f4d449c1bbaaa5eeb9f8a10b4cc7e85.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/avcodec-62-0f4d449c1bbaaa5eeb9f8a10b4cc7e85.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 547. avdevice-62-e71ffbe296e3d34589fb064328316bfc.dll — 62.3.101

- 范围/位置：B；`av.libs/avdevice-62-e71ffbe296e3d34589fb064328316bfc.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/avdevice-62-e71ffbe296e3d34589fb064328316bfc.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 548. avfilter-11-780a5681e7b21881ef585cd5ce000321.dll — 11.14.101

- 范围/位置：B；`av.libs/avfilter-11-780a5681e7b21881ef585cd5ce000321.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/avfilter-11-780a5681e7b21881ef585cd5ce000321.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 549. avformat-62-9c2d3ee2527a13ca0fdcb82b33ed040a.dll — 62.12.101

- 范围/位置：B；`av.libs/avformat-62-9c2d3ee2527a13ca0fdcb82b33ed040a.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/avformat-62-9c2d3ee2527a13ca0fdcb82b33ed040a.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 550. avutil-60-21bd72d722406bd9f4b24262cf4b35f3.dll — 60.26.101

- 范围/位置：B；`av.libs/avutil-60-21bd72d722406bd9f4b24262cf4b35f3.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/avutil-60-21bd72d722406bd9f4b24262cf4b35f3.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 551. libdav1d-d92ea30c3d9c9934f860c34d1ba70766.dll — 7.0.0

- 范围/位置：B；`av.libs/libdav1d-d92ea30c3d9c9934f860c34d1ba70766.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libdav1d-d92ea30c3d9c9934f860c34d1ba70766.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 552. libgcc_s_seh-1-eb70c1c038eb1106448e1bc7e15ae24a.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libgcc_s_seh-1-eb70c1c038eb1106448e1bc7e15ae24a.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libgcc_s_seh-1-eb70c1c038eb1106448e1bc7e15ae24a.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 553. libiconv-2-52797ea4538a440d60943a017fb87a4f.dll — 1.19

- 范围/位置：B；`av.libs/libiconv-2-52797ea4538a440d60943a017fb87a4f.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libiconv-2-52797ea4538a440d60943a017fb87a4f.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 554. libmp3lame-0-7a64829d195e8823e9b581d29ebd8775.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libmp3lame-0-7a64829d195e8823e9b581d29ebd8775.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libmp3lame-0-7a64829d195e8823e9b581d29ebd8775.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 555. libopencore-amrnb-0-39f66c13099c652115aad3e3dbebfd3a.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libopencore-amrnb-0-39f66c13099c652115aad3e3dbebfd3a.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libopencore-amrnb-0-39f66c13099c652115aad3e3dbebfd3a.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 556. libopencore-amrwb-0-715bb0ad19b03fa41dd3753676655d28.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libopencore-amrwb-0-715bb0ad19b03fa41dd3753676655d28.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libopencore-amrwb-0-715bb0ad19b03fa41dd3753676655d28.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 557. libopus-0-b7c59d64d75a04d4907fe3036e46c927.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libopus-0-b7c59d64d75a04d4907fe3036e46c927.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libopus-0-b7c59d64d75a04d4907fe3036e46c927.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 558. libsharpyuv-25eb0c4836aeeccd9b98aeb9ee77a148.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libsharpyuv-25eb0c4836aeeccd9b98aeb9ee77a148.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libsharpyuv-25eb0c4836aeeccd9b98aeb9ee77a148.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 559. libstdc++-6-6cc2d0c6172bc373353f289ef20782fe.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libstdc++-6-6cc2d0c6172bc373353f289ef20782fe.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libstdc++-6-6cc2d0c6172bc373353f289ef20782fe.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 560. libSvtAv1Enc-5eeef79489c86980df49968253b5be77.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libSvtAv1Enc-5eeef79489c86980df49968253b5be77.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libSvtAv1Enc-5eeef79489c86980df49968253b5be77.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 561. libvpl-7122e3918b8fda828a5af6af73ca944b.dll — 2.16.0.0

- 范围/位置：B；`av.libs/libvpl-7122e3918b8fda828a5af6af73ca944b.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libvpl-7122e3918b8fda828a5af6af73ca944b.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 562. libvpx-1-c0f634e6ca42adeec806716d1a9e5c3e.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libvpx-1-c0f634e6ca42adeec806716d1a9e5c3e.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libvpx-1-c0f634e6ca42adeec806716d1a9e5c3e.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 563. libwebp-e5d4f9543eae6d381f6212f006b75bdc.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libwebp-e5d4f9543eae6d381f6212f006b75bdc.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libwebp-e5d4f9543eae6d381f6212f006b75bdc.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 564. libwebpmux-c7c66c64054d42d6a25d9c92afeb2d3f.dll — 准确版本未查明

- 范围/位置：B；`av.libs/libwebpmux-c7c66c64054d42d6a25d9c92afeb2d3f.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libwebpmux-c7c66c64054d42d6a25d9c92afeb2d3f.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 565. libwinpthread-1-26b1e143f68b103d25cd0ba0a146f5b4.dll — 1, 0, 0, 0

- 范围/位置：B；`av.libs/libwinpthread-1-26b1e143f68b103d25cd0ba0a146f5b4.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libwinpthread-1-26b1e143f68b103d25cd0ba0a146f5b4.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 566. libx264-165-71900781b680e0e06a1b966b46fee000.dll — 0.165.x

- 范围/位置：B；`av.libs/libx264-165-71900781b680e0e06a1b966b46fee000.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libx264-165-71900781b680e0e06a1b966b46fee000.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖；新增：pyav-ffmpeg README写x264 32c3b801，但pkg.py固定b35605ac；后者源码SHA已匹配上游脚本，DLL源码对应关系仍未闭合。x2654.2源码和原文已取得，不等于组合授权问题已解决。。

## 567. libx265-7e74dd5103fd9dad5114dffeefd474ce.dll — 4.2+1-e444744

- 范围/位置：B；`av.libs/libx265-7e74dd5103fd9dad5114dffeefd474ce.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/libx265-7e74dd5103fd9dad5114dffeefd474ce.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 568. swresample-6-2f06f0ee7dafc4af6aa424f40df61d57.dll — 6.3.101

- 范围/位置：B；`av.libs/swresample-6-2f06f0ee7dafc4af6aa424f40df61d57.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/swresample-6-2f06f0ee7dafc4af6aa424f40df61d57.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 569. swscale-9-23c45a0fb3712fe0e8e3dafd8d2fd7d1.dll — 9.5.101

- 范围/位置：B；`av.libs/swscale-9-23c45a0fb3712fe0e8e3dafd8d2fd7d1.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/swscale-9-23c45a0fb3712fe0e8e3dafd8d2fd7d1.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 570. zlib1-df406c365e4a532adb993bd06f95ca24.dll — 准确版本未查明

- 范围/位置：B；`av.libs/zlib1-df406c365e4a532adb993bd06f95ca24.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:av.libs/zlib1-df406c365e4a532adb993bd06f95ca24.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 571. libscipy_openblas64_-13e2df515630b4a41f92893938845698.dll — 准确版本未查明

- 范围/位置：B；`numpy.libs/libscipy_openblas64_-13e2df515630b4a41f92893938845698.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:numpy.libs/libscipy_openblas64_-13e2df515630b4a41f92893938845698.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 572. msvcp140-263139962577ecda4cd9469ca360a746.dll — 14.40.33810.0

- 范围/位置：B；`numpy.libs/msvcp140-263139962577ecda4cd9469ca360a746.dll`。
- 许可：未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`native:numpy.libs/msvcp140-263139962577ecda4cd9469ca360a746.dll`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：PE动态依赖；导入边见evidence/pe-imports.json；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：确切来源、license、对应源码或Microsoft再分发依据未逐项闭合；父库的许可证不可自动覆盖。

## 573. Cubic 11 / 俐方体11号 / 俐方體11号 / 俐方體11號 — 1.451

- 范围/位置：A,B；`assets/fonts/Cubic11.ttf`。
- 许可：OFL-1.1。组件版权声明：Copyright(c) 2005 M+ FONTS PROJECT；Copyright (C) 2002-2004 COZ。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:assets/fonts/Cubic11.ttf`。
- 完整原文及现有材料：[Cubic11-OFL.txt](materials/font/Cubic_11_11_11_11-1.451/Cubic11-OFL.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：上游字节版本对应仍需补来源URL。

## 574. Source Han Sans SC Heavy / 思源黑体 Heavy — Version 2.005;addfeatures 5.0.0b21

- 范围/位置：A,B；`assets/fonts/SourceHanSansSC-Heavy.otf`。
- 许可：OFL-1.1。组件版权声明：Copyright 2014-2025 Adobe (http://www.adobe.com/), with Reserved Font。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:assets/fonts/SourceHanSansSC-Heavy.otf`。
- 完整原文及现有材料：[LICENSE.txt](materials/font/Source_Han_Sans_SC_Heavy_Heavy-Version_2.005_addfeatures_5.0.0b21/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：上游字节版本对应仍需补来源URL。

## 575. Source Han Sans SC Medium / 思源黑体 Medium — Version 2.005;addfeatures 5.0.0b21

- 范围/位置：A,B；`assets/fonts/SourceHanSansSC-Medium.otf`。
- 许可：OFL-1.1。组件版权声明：Copyright 2014-2025 Adobe (http://www.adobe.com/), with Reserved Font。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:assets/fonts/SourceHanSansSC-Medium.otf`。
- 完整原文及现有材料：[LICENSE.txt](materials/font/Source_Han_Sans_SC_Medium_Medium-Version_2.005_addfeatures_5.0.0b21/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：上游字节版本对应仍需补来源URL。

## 576. ZCOOL KuaiLe — Version 2.001

- 范围/位置：A,B；`assets/fonts/ZCOOLKuaiLe-Regular.ttf`。
- 许可：OFL-1.1。组件版权声明：Copyright 2018 The ZCOOL KuaiLe Project Authors (https://github.com/googlefonts/zcool-kuaile)。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:assets/fonts/ZCOOLKuaiLe-Regular.ttf`。
- 完整原文及现有材料：[ZCOOLKuaiLe-OFL.txt](materials/font/ZCOOL_KuaiLe-Version_2.001/ZCOOLKuaiLe-OFL.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：上游字节版本对应仍需补来源URL。

## 577. ZCOOL QingKe HuangYou / Õ¾¿áÇì¿Æ»ÆÓÍÌå / 站酷庆科黄油体 — Version 1.000

- 范围/位置：A,B；`assets/fonts/ZCOOLQingKeHuangYou-Regular.ttf`。
- 许可：OFL-1.1。组件版权声明：Copyright 2018 The ZCOOL QingKe HuangYou Project Authors (https://www.github.com/googlefonts/zcool-qingke-huangyou)。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:assets/fonts/ZCOOLQingKeHuangYou-Regular.ttf`。
- 完整原文及现有材料：[ZCOOLQingKeHuangYou-OFL.txt](materials/font/ZCOOL_QingKe_HuangYou-Version_1.000/ZCOOLQingKeHuangYou-OFL.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：上游字节版本对应仍需补来源URL。

## 578. codicon — Version 1.11

- 范围/位置：B；`qtawesome/fonts/codicon-0.0.36.ttf`。
- 许可：CC-BY-4.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/codicon-0.0.36.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/codicon-0.0.36/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 579. elusiveicons — Version 001.000 

- 范围/位置：B；`qtawesome/fonts/elusiveicons-webfont-2.0.ttf`。
- 许可：各图标字体原许可，不能以QtAwesome代码MIT代替。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/elusiveicons-webfont-2.0.ttf`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐。

## 580. Font Awesome 5 Brands Regular — 331.524 (Font Awesome version: 5.15.4)

- 范围/位置：B；`qtawesome/fonts/fontawesome5-brands-webfont-5.15.4.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome5-brands-webfont-5.15.4.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-5.15.4/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 581. Font Awesome 5 Free Regular — 331.524 (Font Awesome version: 5.15.4)

- 范围/位置：B；`qtawesome/fonts/fontawesome5-regular-webfont-5.15.4.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome5-regular-webfont-5.15.4.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-5.15.4/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 582. Font Awesome 5 Free Solid — 331.524 (Font Awesome version: 5.15.4)

- 范围/位置：B；`qtawesome/fonts/fontawesome5-solid-webfont-5.15.4.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome5-solid-webfont-5.15.4.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-5.15.4/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 583. Font Awesome 6 Brands Regular — Version 775.01953125 (Font Awesome version: 6.7.2)

- 范围/位置：B；`qtawesome/fonts/fontawesome6-brands-webfont-6.7.2.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：Copyright (c) 2024 Fonticons, Inc. (https://fontawesome.com)。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome6-brands-webfont-6.7.2.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-6.7.2/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 584. Font Awesome 6 Free Regular — Version 775.01953125 (Font Awesome version: 6.7.2)

- 范围/位置：B；`qtawesome/fonts/fontawesome6-regular-webfont-6.7.2.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：Copyright (c) 2024 Fonticons, Inc. (https://fontawesome.com)。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome6-regular-webfont-6.7.2.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-6.7.2/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 585. Font Awesome 6 Free Solid — Version 775.01953125 (Font Awesome version: 6.7.2)

- 范围/位置：B；`qtawesome/fonts/fontawesome6-solid-webfont-6.7.2.ttf`。
- 许可：Font Awesome Free: fonts OFL-1.1; icons CC-BY-4.0; code MIT。组件版权声明：Copyright (c) 2024 Fonticons, Inc. (https://fontawesome.com)。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/fontawesome6-solid-webfont-6.7.2.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/fontawesome-6.7.2/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 586. Material Design Icons 5.9.55 — Version 1.0

- 范围/位置：B；`qtawesome/fonts/materialdesignicons5-webfont-5.9.55.ttf`。
- 许可：Apache-2.0 (fonts); third-party icon exceptions retained in original。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/materialdesignicons5-webfont-5.9.55.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/materialdesign-5.9.55/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 587. Material Design Icons — Version 1.0

- 范围/位置：B；`qtawesome/fonts/materialdesignicons6-webfont-6.9.96.ttf`。
- 许可：Apache-2.0 (fonts); third-party icon exceptions retained in original。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/materialdesignicons6-webfont-6.9.96.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/materialdesign-6.9.96/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 588. Phosphor — Version 1.3

- 范围/位置：B；`qtawesome/fonts/phosphor-1.3.0.ttf`。
- 许可：MIT。组件版权声明：Copyright (c) 2020 Phosphor Icons。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/phosphor-1.3.0.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/phosphor-license/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 589. remixicon — Version 2.5

- 范围/位置：B；`qtawesome/fonts/remixicon-2.5.0.ttf`。
- 许可：Apache-2.0。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:qtawesome/fonts/remixicon-2.5.0.ttf`。
- 完整原文及现有材料：[LICENSE.txt](materials/fonts/remixicon-2.5.0/LICENSE.txt)
- 用途/集成：TTF/OTF原文件随包与渲染加载；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：字体对应版本完整OFL/MIT/Apache/图标许可、版权与保留字体名称；格式转换/修改记录。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：未找到逐字体许可正文；FontAwesome5/6、Codicon、Elusive、MDI5/6、Phosphor、Remix需分别补齐；对应版本原文已补；字体二进制与上游源资产全量比对及图标例外仍需保持，不泛化为所有图标相同许可。。

## 590. Smiley Sans — 2.0.1 (local provenance)

- 范围/位置：A,B；`assets/fonts/SmileySans-Oblique.woff2`、`renderer/public/fonts/SmileySans-Oblique.woff2`。
- 许可：OFL-1.1。组件版权声明：Copyright (c) 2022--2024, atelierAnchor <https://atelier-anchor.com>,。
- 来源：[对应来源](https://github.com/atelier-anchor/smiley-sans/tree/v2.0.1)。版本依据及SHA见机器索引对应`font:smiley`。
- 完整原文及现有材料：[SmileySans-OFL.txt](materials/font/Smiley_Sans-2.0.1_local_provenance/SmileySans-OFL.txt)
- 用途/集成：原WOFF2文件随包；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：补精确下载来源与文件对应证据。

## 591. Source Han Sans Medium WOFF2 — 2.005 (converted from bundled OTF)

- 范围/位置：A,B；`assets/fonts/SourceHanSansSC-Medium.woff2`。
- 许可：OFL-1.1。组件版权声明：Copyright 2014-2025 Adobe (http://www.adobe.com/), with Reserved Font。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`font:sourcehan-woff`。
- 完整原文及现有材料：[LICENSE.txt](materials/font/Source_Han_Sans_Medium_WOFF2-2.005_converted_from_bundled_OTF/LICENSE.txt)
- 用途/集成：WOFF2原文件随包；修改/补丁：格式转换，保留字形表；renderer/public/fonts/README.md记录无子集化、DSIG省略。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核实OFL保留字体名与格式转换规则；不是仅分发渲染结果。

## 592. ag-psd — 31.0.2

- 范围/位置：A,B；`third_party/cover-psd.cjs`。
- 许可：MIT。组件版权声明：Copyright (c) 2016 Agamnentzar。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`vendored:ag-psd`。
- 完整原文及现有材料：[cover-psd-LICENSE.txt](materials/vendored/ag-psd-31.0.2/cover-psd-LICENSE.txt)；[cover-psd-NOTICE.md](materials/vendored/ag-psd-31.0.2/cover-psd-NOTICE.md)
- 用途/集成：esbuild合并源码/Node转换器；修改/补丁：经过打包minify；自有wrapper为scripts/cover_psd_adapter.cjs。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：ag-psd已记版本，pako/base64-js精确版本及原始构建lock尚未找到。

## 593. pako — 准确版本未查明

- 范围/位置：A,B；`third_party/cover-psd.cjs`。
- 许可：MIT/Zlib; upstream exact version unresolved。组件版权声明：Copyright (C) 2014-2017 by Vitaly Puzrin and Andrei Tuputcyn。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`vendored:pako`。
- 完整原文及现有材料：[cover-psd-pako-LICENSE.txt](materials/vendored/pako-None/cover-psd-pako-LICENSE.txt)；[cover-psd-NOTICE.md](materials/vendored/pako-None/cover-psd-NOTICE.md)
- 用途/集成：esbuild合并源码/Node转换器；修改/补丁：经过打包minify；自有wrapper为scripts/cover_psd_adapter.cjs。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：ag-psd已记版本，pako/base64-js精确版本及原始构建lock尚未找到。

## 594. base64-js — 准确版本未查明

- 范围/位置：A,B；`third_party/cover-psd.cjs`。
- 许可：MIT。组件版权声明：Copyright (c) 2014 Jameson Little。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`vendored:base64-js`。
- 完整原文及现有材料：[cover-psd-base64-LICENSE.txt](materials/vendored/base64-js-None/cover-psd-base64-LICENSE.txt)；[cover-psd-NOTICE.md](materials/vendored/base64-js-None/cover-psd-NOTICE.md)
- 用途/集成：esbuild合并源码/Node转换器；修改/补丁：经过打包minify；自有wrapper为scripts/cover_psd_adapter.cjs。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：ag-psd已记版本，pako/base64-js精确版本及原始构建lock尚未找到。

## 595. 游戏截图/参考图/封面模板 — 准确版本未查明

- 范围/位置：A,B；`assets/design-references/balatro/`、`assets/cover-templates/`。
- 许可：未查明原文件再分发授权。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://www.playbalatro.com/press-kit/)。版本依据及SHA见机器索引对应`assets:game-art`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：原PNG/JPG、裁切图册及含游戏截图的可编辑PSD/XCF随软件分发；修改/补丁：参考图裁切拼接，PSD/XCF嵌入录播冻结帧。
- 源码与配套义务：素材权利人和实际授权范围；软件原件再分发/改作/下游再分发许可。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：press kit与媒体网站图片下载不等于可捆绑素材库；“本轮授权录播截图”未证明永久无限再分发。

## 596. 模型厂商/项目标志 — 准确版本未查明

- 范围/位置：A,B；`assets/`、`website/public/assets/`。
- 许可：商标/版权各自保留，授权范围未查明。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`assets:marks`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：模型工坊识别标志及网站；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：精确文件与来源、商标使用/再分发范围应补到最终资产清单；不要暗示背书。

## 597. Windows System.Speech diagnostic audio — 5.97375 seconds

- 范围/位置：A,B；`assets/diagnostics/speech_en.wav`、`assets/diagnostics/README.txt`。
- 许可：Windows voice-generated output; provenance known, output redistribution terms not verified。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`assets:diagnostic`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：模型准备测试夹具；修改/补丁：合成英文诊断语音；未发现真实私人录音证据。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核实所用系统语音的输出使用条件；不要把它列作用户真实语音泄漏。

## 598. README/网页演示与示例字幕 — 准确版本未查明

- 范围/位置：A；`docs/assets/readme/`、`website/public/assets/woodland.mp4`、`website/deliverables/`。
- 许可：自有编排+第三方品牌/GSAP等需分别确认。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`assets:readme-demo`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：分发渲染输出、网页源码及素材；README不进入当前B；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：本轮检查15个图像文件和5个GIF的首中末采样，共25画面；未OCR全部历史图片/逐帧全部视频；保持原README设计。

## 599. 2ByteASR GIMP cover bridge — local source snapshot

- 范围/位置：A,B；`assets/gimp/2byte-cover-bridge.py`、`assets/gimp/COPYING-GIMP.txt`。
- 许可：GPL-3.0-or-later (explicit local grant)。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`gimp:bridge`。
- 完整原文及现有材料：[COPYING-GIMP.txt](materials/gimp/2ByteASR_GIMP_cover_bridge-local_source_snapshot/COPYING-GIMP.txt)；[RUNTIME-NOTICE.md](materials/gimp/2ByteASR_GIMP_cover_bridge-local_source_snapshot/RUNTIME-NOTICE.md)
- 用途/集成：独立GIMP插件/文件队列；当前封面入口是Qt，完整GIMP不在B；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：现存GPL授权保留；若归属完全自有仍不能撤销既有接受者授权。

## 600. GIMP — 3.2.6 referenced local optional runtime

- 范围/位置：D,E；`assets/gimp/runtime.json`、`scripts/deploy_gimp_runtime.py`。
- 许可：GPL-3.0-or-later and dependencies。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`tool:gimp-external`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：用户另行安装/选择；开发机原运行时存在，但当前B不含tools/gimp-3.2.6；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：不将开发机GIMP全包当成当前Setup组件。

## 601. 随源/随包字幕指导文本 — per-file SHA256

- 范围/位置：A,B；`.agents/skills/2byteskill/SKILL.md`、`.agents/skills/subtitle-theme-aesthetics/SKILL.md`、`assets/design-skills/`。
- 许可：作者自有文本及参考来源需区分。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`skills:shipped`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：直接分发skill/模板文本；不是只分发渲染成片；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：核对文字作者/复制来源；HyperFrames参考提交2be82f00999569e2e2d462a9f3eab57bd36d371e只证明参考版本，非全部授权。

## 602. 本机设计技能/Codex插件工具 — 准确版本未查明

- 范围/位置：E；`.agents/skills/* (except two tracked skills)`、`skills-lock.json`。
- 许可：各自许可，未逐项核实。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`skills:local-only`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：本地开发用；大量技能被gitignore，未在当前B；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：如果未来源ZIP手动包含隐藏目录则重新归A，不得继续称开发专用。

## 603. 用户配置的云ASR/LLM/OSS及CLI服务 — 准确版本未查明

- 范围/位置：D；`twobyteasr/ai_providers.py`、`twobyteasr/spark_asr.py`、`twobyteasr/llm_config.py`。
- 许可：各服务条款；客户SDK另列B。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：**官方精确来源未查明**。版本依据及SHA见机器索引对应`services:external`。
- 完整原文及现有材料：**未取得独立原文**（不是空文件占位）。
- 用途/集成：网络调用或用户安装的CLI；凭据不随包；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：服务品牌、用户同意/数据传输说明与SDK许可分开；未验证外部账户或调用付费接口。

## 604. Inno Setup — 6.7.3

- 范围/位置：B,E；`installer/2ByteASR-frozen.iss`、`Setup embedded installer / installed unins000.exe`。
- 许可：Inno Setup license (BSD-like)。组件版权声明：组件权利人尚未单独核实；完整原文及其各自版权声明保留，不以许可模板作者代替组件作者。
- 来源：[对应来源](https://raw.githubusercontent.com/jrsoftware/issrc/is-6_7_3/license.txt)。版本依据及SHA见机器索引对应`tool:inno`。
- 完整原文及现有材料：[LICENSE.txt](materials/inno/6.7.3/LICENSE.txt)
- 用途/集成：构建工具及安装器/卸载器代码；解包器报格式6.7.0不是构建工具版本；修改/补丁：未证明逐字节未修改。
- 源码与配套义务：对应版本许可全文、版权与适用NOTICE；先核查原文。第三方源码不是一律强制：以该项实际许可为准；当前收集结果和取得方式见SOURCES.md及上列材料。
- 证据/兼容性：有初步证据；自有GPL已采用，旧禁售目标撤销；当前组合与源码问题见GPL3_ROUTE.md。待查：保留实际编译器版本与许可；解包仅验证载荷，不重建安装器。
