# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

洗衣机运行周期数据分析工具：纯前端、可离线运行。上传洗衣机遥测数据（功率 / 累计用水量 / 累计电量），自动识别洗涤周期相位节点，计算能耗水耗并绘制时序图。交付物是单文件 `洗衣机数据分析软件.html`，由 `app.html` 打包而来。

## 常用命令

无构建系统 / 包管理器 / 测试框架，均为 Windows PowerShell 5.1 脚本 + 静态 HTML：

- 打包成单文件 HTML + 生成启动 bat：
  `powershell -File build_software.ps1`
- 本地静态服务器（端口 8765，默认打开 app.html）：
  `powershell -File server.ps1`

脚本均使用 `$PSScriptRoot` 定位自身目录，可在任意位置运行。

## 核心架构

相位检测算法的全部实现都集中在 **`app.html`** 一个文件里：解析管线（`mapColumns` 表头列映射、`parseRows`、`parseExcelRows` / `parseTextRows`）→ 节点识别（`detectNodes`）→ 参数计算（`calcParams`）→ 渲染与自审查（`renderChart` / `renderTable` / `renderVerify`）。`lib/xlsx.full.min.js` 是 SheetJS 库，仅用于解析 Excel 文件，打包时被内联进交付物。

检测节点链：opStart → mainStart（首个 dW>0.001）→ heatStart/heatEnd（P>1000W，低功率加热有滚动窗回退 + 加热器电流闸门）→ 各次漂洗进水（burst ≥0.3 L，节点 = 脉冲前 1 s，含补水切除/合并/均匀性自检）→ spinStart（排水静默→电机启动，四级回退）→ spinHiE（P>300 末段或 P≥60 活动段终点）→ opEnd（连续静默 + 平台预检/脉冲回退）。完整权威规则见 `README.md`「算法判定规则」。

## 数据格式

原始数据是 GBK（代码页 936）编码的制表符分隔文本（`.tsv`，部分 `.xls` 实为文本），也支持 Excel（`.xlsx` / `.xls`）。**前端按表头自动映射列名，无需手工指定列号**；必备字段为时间戳、功率(W)、累计用水量(L)、累计电量(kWh)，可选加热器电流(A)、转速(rpm) 等。

## 编码注意事项（易踩坑）

- 数据解码由浏览器端 `TextDecoder` 完成（GBK / UTF-8 自动识别），无需在脚本侧处理。
- `build_software.ps1` 用码点拼接中文文件名、启动 bat 用 GBK（936）写出，都是为了规避 PowerShell 5.1 对无 BOM 中文源文件乱码的问题。

## 文档

- `README.md` —— 项目说明 + 使用方法 + 数据格式 + 算法判定规则（权威）+ 构建方式。
