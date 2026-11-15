#!/bin/bash
# 双击这个文件就能开玩《忍者风暴竞技场》。
# 第一次运行时 macOS 可能会问"是否允许访问'文稿'文件夹"，选允许即可。

cd "$(dirname "$0")" || exit 1

APP="/Applications/Godot.app"
GODOT="/opt/homebrew/bin/godot"
if [ ! -x "$GODOT" ]; then
	echo "没找到 Godot：$GODOT"
	echo "请先安装 Godot 4.7+：brew install --cask godot"
	echo "或从 https://godotengine.org/download/macos 下载后拖进 Applications。"
	read -r -p "按回车关闭…"
	exit 1
fi

echo "启动《忍者风暴竞技场》…"
echo "P1：A/D 移动，W 跳，S 防御，J 攻击，K 忍术；F2 切 CPU/双人；R 重开；ESC 退出"
"$GODOT" --path "$(pwd)"
