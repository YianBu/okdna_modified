# AGENTS.md

给在本仓库工作的 AI 助手的规则。

## 绝不触碰上游（硬性）

- `origin` = `https://github.com/BnanZ0/ok-duet-night-abyss.git` 是上游。**永远不要** push 到
  `origin`、不要向上游开 PR、不要改上游的分支或远程配置。
- 所有提交只推 `mine` = `https://github.com/YianBu/okdna_modified.git` 的 `master`：
  `git push mine master`。
- 本地 `master` 仍跟踪 `origin/master`，只为 `git pull` 拉上游更新；仓库已设
  `remote.pushDefault = mine`，所以不带参数的 `git push` 也只会打到 `mine`。
- 本地 `origin` 另设了 `remote.origin.tagOpt = --no-tags`：`git pull/fetch` 只拉上游的
  提交，不会把上游那一百多个 tag（`v0.0.x`/`v1.0.x`/`v1.1.x`…`v1.6.x`）抓回本地。
  这是刻意设的**本地**配置（不改上游任何东西、也不影响推送 tag），不要删。

## 提交前

- **不必**跑测试：用户明确说过「这些测试没有跑的必要」。CI 在打 tag 之后会逐个执行
  `tests/test_*.py` 兜底。需要本地自查时命令是
  `python -m unittest tests/test_ui_labels.py`、`tests/test_theatre_task.py`、
  `tests/test_heavy_attack.py`。
- 文案**只维护中文**：新增用户可见配置/文案时，往 `i18n/zh_CN/LC_MESSAGES/ok.po` 加
  `msgid` 就行（该文件 `msgstr` 惯例留空 = 回落到中文原文）；其它五种语言不用再动。

## 提交信息

- 提交信息只写「这个版本增加了、改了哪些内容」，一两句（一到三行）说清就行。
- 不要把实现细节、排查过程、踩过的坑、设计取舍写进提交信息；那些留在与用户的对话里，
  需要留档就写进代码注释或本文件。

## 看图片（直接看，看不清再 OCR）

- 助手**能直接看到图片**（视觉通道可用），用户发的截图正常按图聊就行，不要凭文件名或
  描述猜内容。只有图太小、太糊，或需要逐字的精确坐标时才走下面的 OCR。
- 命令：`python tools/ocr_image.py <图片路径> --out 结果.txt`，输出每行
  `x1,y1,x2,y2 <TAB> 置信度 <TAB> 文本`（坐标是图片像素，按 1600×900 基准的框换算前先看长边）。
- 引擎是本机 Python（`C:\Users\67400\AppData\Local\Programs\Python\Python313`，
  也就是 ok 源码版用的那个）里随 `ok` 装好的 PP-OCRv5（`onnxocr` 包，模型随包离线可用）。
  默认走 `use_openvino=True` 的 OpenVINO 后端（和 ok 源码版一致）；`onnxruntime`
  和 `rapidocr` 也已装好，可用 `--backend onnxruntime` 或改用 rapidocr 对照。
- 终端是 GBK，中文直接打印会乱码：加 `--out` 写成 UTF-8，再用
  `Get-Content -Encoding UTF8` 读回来。

## 部署到本地（默认自动做）

- 用户本地跑的是**源码方式**：`E:\360MoveData\Users\67400\Desktop\ok-dna` 里放了一份
  `main.py` + `src`，和现成的 `assets`/`i18n`/`mod`/`configs` 共用；启动器是目录里的
  `start-source.bat`（用本机 Python 的 `pythonw` 跑源码）。目录里那个 `ok-dna.exe`
  是旧的冻结包，只在需要冻结版时才用。
- **改完代码就自动同步过去**，不用等用户说「部署」：整份替换该目录下的 `src`，再覆盖
  `main.py`；动了中文文案就把 `i18n/zh_CN/LC_MESSAGES/ok.po` 也覆盖过去。只动这几处，
  别碰 `configs`（用户配置）、`logs`、以及 `mod` 里用户自己加的东西。
- 同步是秒级的文件拷贝；Python 不会热加载，**要重启那个源码版程序**新代码才生效，
  同步完在回复里提醒用户重启（只改任务配置的话，重新开始任务即可）。
- 本地打包（PyInstaller，约 3~5 分钟）只在用户明确要求、或要出冻结版/发布时做；
  打包脚本是仓库里的 `build_exe.spec`。

## 版本与发布

- 本仓库的版本号（`v1.x`）与上游完全独立，不要拿上游的 tag 做比较或参考。
  本仓库自己的发布序列到目前是 `v1.0.1`…`v1.1.2`（另有 CI 用的
  `launcher-base-v1.0.1`，在远端，不是版本号）。本地 tag 已清理过，只剩本仓库自己的 `v1.x`，
  `origin` 也设了 `tagOpt = --no-tags`，所以 `git pull` 不会再带回上游的 tag；
  万一又看到上游 tag（换了机器、重新克隆等），别照它们编号，本地删掉即可。
- 版本号**逢 10 进 1**：`v1.0.9` 之后是 `v1.1.0`（不是 `v1.0.10`），`v1.1.9` 之后是
  `v1.2.0`，以此类推。
- `v1.1.3` 这个号打过一次又被删掉了：`v1.1.2` 第一次的 CI 挂在「Run tests」步骤（1 分多钟
  就失败、Release 被跳过），用户把版本号改回 `v1.1.2` 重新推了一次。现在远端和本地都没有
  `v1.1.3` 这个 tag，下一个可用的号仍然是它。
- **「传云」的含义**：用户说「传云」（或「传云 git」「推送更新」）时，默认理解为
  「提交改动 -> 本仓库版本号 +1 打 annotated tag -> 推送」：即
  `git push mine master` 加 `git push mine <下一个版本号>`（当前下一个是 `v1.1.3`），
  让 CI 出 release 给 Launcher 用户。**只推这一个 tag，绝不 `--tags`**。
  推完把下一个版本号记住（再次「传云」时就再 +1）。
- 发布 = 打 `v*` tag 推到 `mine`：CI 按 tag 改写 `src/config.py` 的 version 并发布
  release，Launcher 用户就是靠这个 tag 才拿得到更新的。
- 永远不要 `git push mine --tags`：`git pull` 之后本地会重新带回上游的 `v1.6.x` 等标签，
  全推上去会让 Launcher 把 `v1.6.5` 当成「新版本」推给用户。推发布 tag 要指名道姓，
  一次只推要发的那一个。
- 一次发布约 12 分钟，其中约 9 分钟是 PyAppify 最后 `makensis` 压缩 ~590MB 的离线
  payload（Python 环境 + 依赖 + 源码快照）。这是已知且**已接受**的成本，不要再为了
  「省时间」把它改成只发 online 安装包、或省掉打包。
- `use_release` 复用已编译的 Launcher，依赖 `launcher-base-v1.0.1` 这个**已公开发布的
  预发布** release：action 是去下载它的资产，draft 的下载地址取不到（会 404）。改了
  `icons/` 或 `pyappify.yml` 之后这个 zip 就失效了，需要重新出一个包并更新里面的 tag。
