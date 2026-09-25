# ok-dna Modified

这是基于 [ok-duet-night-abyss](https://github.com/BnanZ0/ok-duet-night-abyss) 修改的 ok-dna 版本，使用与原版相同的 Launcher 安装和自动更新方式。

## 下载安装

推荐国内网络下载完整安装包：

[![下载 China 完整安装包](https://img.shields.io/badge/下载-China%20完整安装包-2ea44f?style=for-the-badge)](https://github.com/YianBu/okdna_modified/releases/latest/download/ok-dna-win32-China-setup.exe)

海外网络可使用 Global 完整安装包：

[![下载 Global 完整安装包](https://img.shields.io/badge/下载-Global%20完整安装包-0969da?style=for-the-badge)](https://github.com/YianBu/okdna_modified/releases/latest/download/ok-dna-win32-Global-setup.exe)

如果希望先下载一个很小的在线安装器，也可以使用：

[![下载在线安装包](https://img.shields.io/badge/下载-在线安装包-f6a311?style=for-the-badge)](https://github.com/YianBu/okdna_modified/releases/latest/download/ok-dna-win32-online-setup.exe)

> 普通用户推荐使用 China 完整安装包。下载后双击运行，按照安装器提示完成安装即可。

## 自动更新

Launcher 的代码更新地址在 [`pyappify.yml`](pyappify.yml) 中配置，目前为：

```text
https://github.com/YianBu/okdna_modified.git
```

安装后无需反复下载安装包：

1. Launcher 会从当前仓库获取最新代码。
2. 本仓库 `master` 分支更新后，已安装用户可以获取最新代码。
3. 依赖或 Launcher 本体需要变化时，再发布一个新的 `v*` 标签即可。

## 手动发布新版本

在工作区修改并提交后，推送 `master`：

```powershell
git push mine master
```

然后创建并推送版本标签，GitHub Actions 会自动构建并发布安装包：

```powershell
git tag v1.7.0
git push mine v1.7.0
```

构建完成后，在 [Releases](https://github.com/YianBu/okdna_modified/releases) 页面即可看到新的 Launcher 安装包。

## 从源码运行

仅建议开发调试时使用：

```powershell
python -m pip install -r requirements.txt
python main.py
```

