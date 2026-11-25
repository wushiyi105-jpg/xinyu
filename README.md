# 心语 xinyu

[![test](https://github.com/wushiyi105-jpg/xinyu/workflows/test/badge.svg)](https://github.com/wushiyi105-jpg/xinyu/actions)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![codecov](https://codecov.io/gh/wushiyi105-jpg/xinyu/branch/main/graph/badge.svg)](https://codecov.io/gh/wushiyi105-jpg/xinyu)

![示例](assets/demo.gif)

每天写一段,给情绪打个分,找出压力源头,再看这段时间的走势。

我做这个不是为了"管理情绪"这种虚话。真实的原因是:我经常觉得自己"最近状态不好",但说不出从哪天开始、被什么拖下去的。心语只做三件能验证的事——**给你写下的字打分、把压力源对应到具体那句话、把一段时间的均值与波动算给你看**。

## 功能特性

- **每日一条**:按日期存,同一天再记就覆盖,不留重复行。
- **情绪打分**:词表打分,范围 -5 到 5;模型可以给更具象的情绪名,但分数越界会被截断。
- **压力源带证据**:每个压力源必须附一句原文,查不到就丢——避免"可能你最近压力大"这类没法核对的判断。
- **建议可执行**:最多 4 条,每条不超过 40 字,要具体到动作。不做诊断、不提药物。
- **趋势**:均值、波动(标准差)、最好/最难的一天、连续低落天数,全部本地算;模型只写一段解读,并禁止出现统计里没有的数字。
- **离线模式**:词表 + 关键词 + 分档建议,明说"只基于你写下的字,不做推断"。
- **双入口**:CLI 与网页,数据都在本机。

## 快速开始

```bash
git clone https://github.com/wushiyi105-jpg/xinyu.git
cd xinyu
python -m xinyu add today.txt --date 2026-11-25
python -m xinyu analyze 2026-11-25
python -m xinyu trend --days 7
```

接模型:

```bash
cp .env.example .env
# 填 LLM_API_KEY,默认 https://api.deepseek.com + deepseek-flash
```

```bash
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 LLM_MODEL=glm-4.6 python -m xinyu analyze 2026-11-25
```

网页:

```bash
python -m xinyu web --port 8768
# http://127.0.0.1:8768
```

## 命令参考

| 命令 | 作用 |
| --- | --- |
| `add <file> [--date]` | 记一条,`-` 从 stdin 读,默认今天 |
| `list [--limit]` | 最近记录 |
| `show <日期或 id>` | 看某一天的全文与分析 |
| `analyze <日期或 id>` | 分析并存库 |
| `trend [--days 7]` | 趋势 |
| `rm <key>` / `stats` | 删除 / 统计 |
| `web` | Web UI |

全局开关 `--mock`、`--json`、`--model`、`--base-url`、`--api-key`、`--db`,前后都能放。

## 工作原理

```mermaid
flowchart TD
    CLI["cli.py<br/>argparse 子命令"] --> AGENT
    WEB["web.py<br/>ThreadingHTTPServer + 单页"] --> AGENT
    AGENT["agent.py<br/>analyze / trend"] -->|有 key| LLM["llm.py<br/>urllib 直连 /chat/completions"]
    AGENT -->|无 key 或 --mock| MOCK["mock.py<br/>词表打分 / 关键词 / 分档建议"]
    AGENT --> CHECK["tools.py<br/>情绪词表 / 压力源 / 趋势算术"]
    CHECK --> DB["db.py<br/>entries 按日期唯一,threading.Lock"]
```

三处取舍:

1. **分数与算术不给模型改**。情绪词的倾向和均值、标准差是能算的;模型负责给情绪起名、把压力源说成人话,但 `score` 越界直接截断,趋势总结里冒出统计外的数字就换回本地解读。
2. **证据必须能回查**。压力源的关键词命中了哪句,就把那句原样抄出来;抄不出来说明是模型自己编的,直接丢。
3. **不做诊断,也不装医生**。建议只给动作(散步、拆任务、写下来),不说"你应该去看心理医生"以外的医疗判断;真需要专业帮助,它也不会假装能替代。

SQLite 单文件,`check_same_thread=False` + `threading.Lock`,默认 `data/xinyu.db`,`XINYU_DB` 可改。

## 目录结构

```
xinyu/
├── xinyu/
│   ├── __init__.py / __main__.py
│   ├── llm.py     # OpenAI 兼容客户端 + .env 加载
│   ├── db.py      # entries(日期唯一,线程安全)
│   ├── tools.py   # 情绪词表、压力源、趋势算术、证据回查
│   ├── mock.py    # 离线分析与趋势文案
│   ├── agent.py   # 分析与趋势编排
│   ├── cli.py     # 命令行
│   └── web.py     # Web UI
├── data/entries-sample.json
├── tests/test_xinyu.py
├── assets/demo.gif
├── .github/workflows/test.yml
├── pyproject.toml
├── README.md / README.en.md
└── CHANGELOG.md / SECURITY.md / CODE_OF_CONDUCT.md / CONTRIBUTING.md
```

## 作者

shiyi · GitHub [@wushiyi105-jpg](https://github.com/wushiyi105-jpg) · wushiyi105@gmail.com

MIT License,Copyright (c) 2026 wushiyi105-jpg
