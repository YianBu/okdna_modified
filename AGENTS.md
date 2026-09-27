# AGENTS.md

给在本仓库工作的 AI 助手的规则。

## 绝不触碰上游（硬性）

- `origin` = `https://github.com/BnanZ0/ok-duet-night-abyss.git` 是上游。**永远不要** push 到
  `origin`、不要向上游开 PR、不要改上游的分支或远程配置。
- 所有提交只推 `mine` = `https://github.com/YianBu/okdna_modified.git` 的 `master`：
  `git push mine master`。
- 本地 `master` 仍跟踪 `origin/master`，只为 `git pull` 拉上游更新；仓库已设
  `remote.pushDefault = mine`，所以不带参数的 `git push` 也只会打到 `mine`。

## 提交前

- 跑 `python -m unittest tests/test_ui_labels.py`、`tests/test_theatre_task.py`、
  `tests/test_heavy_attack.py`（CI 逐个执行 `tests/test_*.py`）。
- 动到用户可见配置/文案时，同步六种语言 `i18n/<lang>/LC_MESSAGES/ok.po` 并重编译
  `ok.mo`。`.mo` 只写有译文的条目（zh_CN 的 `msgstr` 惯例留空、回落到中文原文），
  en_US 另外存一份把 msgid 里空格去掉的副本。

## 版本与发布

- 本仓库的版本号（`v1.0.x`）与上游完全独立，不要拿上游的 tag 做比较或参考。
- 发布 = 打 `v*` tag 推到 `mine`：CI 按 tag 改写 `src/config.py` 的 version 并发布
  release，Launcher 用户就是靠这个 tag 才拿得到更新的。
- 永远不要 `git push mine --tags`：本地残留着上游的 `v1.6.x` 等标签，全推上去会让
  Launcher 把 `v1.6.5` 当成「新版本」推给用户。
- 一次发布约 12 分钟，其中约 9 分钟是 PyAppify 最后 `makensis` 压缩 ~590MB 的离线
  payload（Python 环境 + 依赖 + 源码快照）。这是已知且**已接受**的成本，不要再为了
  「省时间」把它改成只发 online 安装包、或省掉打包。
- `use_release` 复用已编译的 Launcher，依赖 `launcher-base-v1.0.1` 这个**已公开发布的
  预发布** release：action 是去下载它的资产，draft 的下载地址取不到（会 404）。改了
  `icons/` 或 `pyappify.yml` 之后这个 zip 就失效了，需要重新出一个包并更新里面的 tag。
