# Singularity Advisor

Cell to Singularity 限时活动最优决策辅助工具。实时读取游戏存档，推荐性价比最高的购买顺序。

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
python main.py
```

程序会自动监听存档文件，每次存档更新时在终端打印当前货币和购买建议。

## 配置

编辑 `config.json`：
- `save_dir`：存档目录路径（默认已配置为 Windows 默认路径）
- `save_files`：两个存档文件名（一般不需要修改）
- `top_n`：显示前 N 条建议（默认 3）

## 存档路径

`C:\Users\<用户名>\AppData\LocalLow\Computer Lunch\Cell To Singularity\`
