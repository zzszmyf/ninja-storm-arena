#!/bin/bash
# 双击用 Godot 编辑器打开本项目，方便边改边看。

cd "$(dirname "$0")" || exit 1

APP="/Applications/Godot.app"
GODOT="/opt/homebrew/bin/godot"
if [ ! -x "$GODOT" ]; then
	echo "没找到 Godot：$GODOT"
	read -r -p "按回车关闭…"
	exit 1
fi

"$GODOT" --editor --path "$(pwd)"
