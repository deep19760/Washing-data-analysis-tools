# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

洗衣机运行周期数据分析工具：前后端分离架构。上传洗衣机遥测数据，识别洗涤周期相位节点，计算能耗水耗并绘制时序图。支持「能效」和「程序检查」两种测试类型。

## 常用命令

无构建系统 / 包管理器 / 测试框架，零第三方依赖：

- 启动服务：`python backend/server.py`（端口 3000，浏览器打开 http://localhost:3000）

## 核心架构

前后端分离，接口为 `POST /analyze`（接收 `{ filename, content(base64), testType }`，按 `testType` 分发）：

- **后端 `backend/`**（Python 3，纯标准库）
  - `server.py`：HTTP 服务（GET 静态前端 + POST /analyze + 节点/参数/图表序列化），基于 `http.server`
  - `parser.py`：能效数据解析（GBK/UTF-8 文本，列名自动映射）
  - `efficiency.py`：能效算法（`detect_nodes` / `calc_params`）
  - `program_check.py`：程序检查算法（主洗/漂洗/脱水判定）
- **前端 `frontend/index.html`**：上传 + 测试类型下拉框 + 结果渲染（Canvas 图表），纯 HTML/JS，与后端语言无关

## 数据格式

- **能效数据**：文本（GBK/UTF-8 TSV/CSV，含伪装 `.xls` 的制表符文本），必备字段 时间戳/功率/累计用水量/累计电量（列名自动匹配，见 `parser.py` 的 `map_columns`）。二进制 Excel 暂不支持。
- **程序检查数据**：12 列 GBK TSV，固定列位（0-based）：主洗阀电流=1、排水泵电流=3、加热器电流=5、温度1=6、温度2=7、转速=8、功率=11（见 `program_check.py`）。

## 程序检查算法关键规则（易踩坑）

- **主洗涤结束**：排水泵电流首次大幅上升（基线×1.5，30s 内 ≥3 样本）。基线取前 60 秒最大值；阈值用纯相对值（`base*1.5`），**不要**加绝对最小偏移（`+0.005` 对排水泵电流极低的机型太苛刻）。
- **漂洗次数**：主洗阀电流（列1）代表进水，阈值取「整个周期最大值的 50%」（不能用前 60 秒，进水可能 60 秒后才开始）；漂洗进水 = 主洗结束后、最终脱水前的进水段。
- **温度列选择**：剔除全零列或含异常值（<0 或 >100℃）列，取剩余可用列。
- **最终脱水**：最后一段转速 ≥300 的连续段（gap ≤60s 合并），加速起点往前回溯到转速 ≤120。

## 编码注意事项

- 数据解码：`bytes.decode('utf-8', errors='replace')`，统计 `�`（U+FFFD）个数 >5 则改用 GBK（见 `parser.py` 的 `parse_file`）。
- `js_round(x)`（`math.floor(x + 0.5)`）用于复刻 JS 的 `Math.round`——**不要**直接用 Python 的 `round()`，后者是银行家舍入（0.5 取偶），对拍时会差 0.1。
- 算法是逐行从 JS 转化来的，注意两处语义差异：JS `arr[-1]` 是 `undefined`，Python 是最后一个元素；JS 数组越界返回 `undefined`（比较为 false），Python 抛 `IndexError`。滑动窗口循环的边界要用 `min(i+k, n-1)` 显式保护。

## 文档

- `README.md`：项目说明 + 使用方法 + 数据格式 + 算法规则摘要。
