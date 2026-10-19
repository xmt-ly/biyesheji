# 本轮实际被测源码快照

此目录按真实调用开始时的冻结 SHA 保存源码，不能用交付后的兼容修订替换这里的文件。snapshot-manifest.json 逐项列出原文 SHA；freeze-at-run.json 是本轮冻结锁，亦包含在外层 manifest.freeze 中。

此快照不是完整独立安装包。复现时先在另一个全新目录解压对应交付源码，再按相对路径放入这里的 backend 与 experiments 文件，并将 freeze-at-run.json 作为该轮专用锁传入 --freeze-lock。先离线核对26项源码 SHA 和原轮锁，不在正在使用的工作区覆盖生产文件，不使用真实业务库。

外层 records.json、attempts、summary.json 的真实状态与评分保留；后续兼容修订、离线回放不能改写这些结果。原轮6例×2组×2次共24项，不含回放。重做真实调用需另选新目录、明确免费额度与预算，不能覆盖当前结果。
