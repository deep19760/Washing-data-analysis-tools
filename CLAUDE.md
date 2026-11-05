# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

洗衣机运行周期数据分析工具：前后端分离架构。上传洗衣机遥测数据，识别洗涤周期相位节点，计算能耗水耗并绘制时序图。支持「能效」和「程序检查」两种测试类型。

## 常用命令

无构建系统 / 包管理器 / 测试框架，零 npm 依赖：

- 启动服务：`node backend/server.mjs`（端口 3000，浏览器打开 http://localhost:3000）

## 核心架构

前后端分离，接口为 `POST /analyze`（接收 `{ filename, content(base64), testType }`，按 `testType` 分发）：

- **后端 `backend/`**
  - `server.mjs`：HTTP 服务（GET 静态前端 + POST /analyze + 节点/参数/图表序列化）
  - `analyzer/parse.mjs`：能效数据解析（GBK/Excel，列名自动映射）
  - `analyzer/efficiency.mjs`：能效算法（`detectNodes` / `calcParams`）
  - `analyzer/program-check.mjs`：程序检查算法（主洗/漂洗/脱水判定）
- **前端 `frontend/index.html`**：上传 + 测试类型下拉框 + 结果渲染（Canvas 图表）
- **`lib/xlsx.full.min.js`**：SheetJS 0.18.5，被 `parse.mjs` 用 `createRequire` 加载

## 数据格式

- **能效数据**：Excel/文本，必备字段 时间戳/功率/累计用水量/累计电量（列名自动匹配，见 `parse.mjs` 的 `mapColumns`）。
- **程序检查数据**：12 列 GBK TSV，固定列位（0-based）：主洗阀电流=1、排水泵电流=3、加热器电流=5、温度1=6、温度2=7、转速=8、功率=11（见 `program-check.mjs`）。

## 程序检查算法关键规则（易踩坑）

- **主洗涤结束**：排水泵电流首次大幅上升（基线×1.5，30s 内 ≥3 样本）。基线取前 60 秒最大值；阈值用纯相对值（`base*1.5`），**不要**加绝对最小偏移（`+0.005` 对排水泵电流极低的机型太苛刻）。
- **漂洗次数**：主洗阀电流（列1）代表进水，阈值取「整个周期最大值的 50%」（不能用前 60 秒，进水可能 60 秒后才开始）；漂洗进水 = 主洗结束后、最终脱水前的进水段。
- **温度列选择**：剔除全零列或含异常值（<0 或 >100℃）列，取剩余可用列。
- **最终脱水**：最后一段转速 ≥300 的连续段（gap ≤60s 合并），加速起点往前回溯到转速 ≤120。

## 编码注意事项

- 数据解码用 Node 内置 `TextDecoder`（GBK/UTF-8 自动识别，`parse.mjs` 的 `parseFile` 用 `�` 计数判断乱码）。
- Excel 解析用项目内 `lib/xlsx.full.min.js`（`type:'buffer'`）。

## 文档

- `README.md`：项目说明 + 使用方法 + 数据格式 + 算法规则摘要。
