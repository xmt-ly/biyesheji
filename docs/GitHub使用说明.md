# GitHub 使用说明

仓库地址：<https://github.com/xmt-ly/biyesheji>。首次上传使用私有仓库，默认分支为 `main`。

## 仓库内容

仓库保存前后端源码、依赖清单、测试、辅助脚本、设计文档、论文初稿、答辩材料和实验原始记录。实验使用合成样例，历史结果按原样保存，完整结果与限制见 [交付修订版复验结果](交付修订版复验结果.md)。

`.env`、`.env.stitch`、运行数据库、JWT 密钥、附件数据、备份、`work/`、依赖目录和前端构建产物不上传。本机文件保留在原位置。配置模板 `.env.example` 可以提交，真实密钥只在本机配置。

## 在其他目录获取项目

先在本机完成 GitHub 登录，再运行：

```powershell
git clone https://github.com/xmt-ly/biyesheji.git
Set-Location .\biyesheji
```

安装、启动和演示步骤见 [启动与演示说明](启动与演示说明.md)。Python 路径需要匹配本机环境，其他电脑不一定存在原开发环境 `D:\Anaconda3\envs\face_env\python.exe`。从根目录配置模板创建自己的 `.env`，不要复制其他人的凭据。

仓库通过 `.gitattributes` 保留文件的原始换行，避免实验冻结清单的字节哈希因克隆时转换换行而失效。请勿在未更新对应实验版本的情况下批量转换冻结源码的编码或换行。

## 后续提交

在项目目录执行；提交前先检查修改和暂存内容：

```powershell
git status
git diff
git add <本次修改的文件或目录>
git diff --cached --stat
git commit -m "feat(任务): 添加具体功能说明"
git push
```

更换电脑后，可以在工作区无未保存修改时使用 `git pull --ff-only` 获取更新。GitHub 仅保存已提交并推送的内容，不包含被忽略的业务数据；数据库与附件仍须使用项目备份脚本单独备份。
